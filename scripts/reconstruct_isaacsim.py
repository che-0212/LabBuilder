#!/usr/bin/env python3
"""
重新合成 Isaac Sim 布局文件
从现有的中间文件（room.json 和各个 desktop layout）合并生成最终的 room_isaacsim.json
不需要调用 LLM，只是重新合并已有的布局数据
"""

import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LayoutReconstructor:
    """布局重建器 - 从中间文件重新合成 Isaac Sim 格式"""
    
    def __init__(self, asset_library_path: str = None):
        """
        Args:
            asset_library_path: assets_annotated.json 路径（可选）
        """
        self.assets_by_name = {}
        
        # 如果提供了资产库路径，加载它
        if asset_library_path and Path(asset_library_path).exists():
            self._load_asset_library(asset_library_path)
        else:
            logger.warning("Asset library not provided or not found, will use default values")
    
    def _load_asset_library(self, asset_library_path: str):
        """加载 assets_annotated.json 资产库"""
        logger.info(f"Loading asset library from: {asset_library_path}")
        
        with open(asset_library_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for asset in data['assets']:
            name = asset['name']
            if name not in self.assets_by_name:
                self.assets_by_name[name] = []
            self.assets_by_name[name].append(asset)
        
        logger.info(f"Loaded {len(self.assets_by_name)} unique asset names")
    
    def get_asset_info(self, asset_name: str, asset_type: str = None) -> Dict:
        """获取资产信息"""
        if asset_name not in self.assets_by_name:
            return None
        
        assets = self.assets_by_name[asset_name]
        
        # 如果指定了类型，优先返回匹配类型的
        if asset_type:
            for asset in assets:
                if asset.get('type') == asset_type:
                    return asset
        
        # 否则返回第一个
        return assets[0]
    
    def reconstruct(self, layout_dir: Path, output_path: Path = None) -> Dict:
        """
        重新合成 Isaac Sim 布局
        
        Args:
            layout_dir: 包含中间文件的目录
            output_path: 输出文件路径（可选，如果为None则自动生成）
            
        Returns:
            合成后的布局数据
        """
        logger.info(f"Reconstructing Isaac Sim layout from: {layout_dir}")
        
        # 查找所需的文件
        room_json = None
        desktop_layouts = {}
        experiment_name = "Unknown Experiment"
        
        # 遍历目录查找文件
        for file_path in layout_dir.glob("*.json"):
            filename = file_path.name
            
            if filename.endswith("_room.json"):
                # 房间布局文件
                logger.info(f"Found room layout: {filename}")
                with open(file_path, 'r', encoding='utf-8') as f:
                    room_json = json.load(f)
                # 从文件名提取实验名称
                experiment_name = filename.replace("_room.json", "").replace("_", " ")
            
            elif filename.endswith("_layout.json") and not filename.endswith("_room_layout.json"):
                # 桌面布局文件
                surface_name = filename.split("_")[-2]  # 提取 surface 名称
                logger.info(f"Found desktop layout for {surface_name}: {filename}")
                with open(file_path, 'r', encoding='utf-8') as f:
                    desktop_layouts[surface_name] = json.load(f)
        
        # 检查必需文件
        if room_json is None:
            raise FileNotFoundError(f"Room layout file (*_room.json) not found in {layout_dir}")
        
        logger.info(f"Found {len(desktop_layouts)} desktop layouts")
        
        # 从 room_json 中提取实验名称（如果有）
        if 'experiment_name' in room_json:
            experiment_name = room_json['experiment_name']
        
        # 合成 Isaac Sim 布局
        final_layout = self._create_isaacsim_layout(
            room_json, 
            desktop_layouts, 
            experiment_name
        )
        
        # 保存输出
        if output_path is None:
            # 自动生成输出路径
            base_name = layout_dir.name.split("_2026")[0]  # 去掉时间戳
            output_path = layout_dir / f"{base_name}_room_isaacsim.json"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(final_layout, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✓ Isaac Sim layout reconstructed: {output_path}")
        logger.info(f"  Total objects: {len(final_layout['objects'])}")
        
        return final_layout
    
    def _create_isaacsim_layout(
        self,
        room_layout: Dict,
        desktop_layouts: Dict,
        experiment_name: str
    ) -> Dict:
        """合并 room 和 desktop 布局，生成 Isaac Sim 格式"""
        
        objects = []
        total_desktop_items = 0
        
        # 添加 room 资产
        for item in room_layout['room_layout']:
            name = item['name']
            pos = item['position']
            rot = item.get('rotation_deg', {'x': 0, 'y': 0, 'z': 0})
            
            # 获取资产信息
            asset_info = self.get_asset_info(name, 'room_asset')
            asset_id = asset_info['id'] if asset_info else name
            initial_location = asset_info['initial_location'] if asset_info else 'floor'
            
            objects.append({
                "id": asset_id,
                "position": {
                    "x": pos['x'],
                    "y": pos['y'],
                    "z": pos['z']
                },
                "rotation": {
                    "x": rot['x'],
                    "y": rot['y'],
                    "z": rot['z']
                },
                "initial_location": initial_location
            })
        
        # 为每个 work surface 添加 desktop 资产
        for surface_name, desktop_layout in desktop_layouts.items():
            # 获取 work surface 位置
            surface_position = None
            surface_rotation_z = 0
            
            for item in room_layout['room_layout']:
                if item['name'] == surface_name:
                    surface_position = item['position']
                    surface_rotation_z = item.get('rotation_deg', {}).get('z', 0)
                    break
            
            if surface_position is None:
                logger.warning(f"{surface_name} not found in room layout, skipping")
                continue
            
            # 获取 surface 资产信息
            surface_asset_info = self.get_asset_info(surface_name, 'room_asset')
            if not surface_asset_info:
                logger.warning(f"Surface asset info not found: {surface_name}, using default dimensions")
                # 使用布局中提供的尺寸
                surface_dimensions = desktop_layout.get('surface_dimensions', {})
                surface_width = surface_dimensions.get('width', 2.0)
                surface_depth = surface_dimensions.get('depth', 1.0)
                surface_height = surface_dimensions.get('height', 0.8)
            else:
                surface_bbox = surface_asset_info['geometry']['bbox']
                
                # 根据旋转计算有效的宽度和深度
                # 0°/180°：长边平行于X轴 → width(X方向) = long, depth(Y方向) = short
                # 90°/270°：长边平行于Y轴 → width(X方向) = short, depth(Y方向) = long
                if surface_rotation_z in [90, 270, -90, -270]:
                    surface_width = surface_bbox['short']  # X方向 = short
                    surface_depth = surface_bbox['long']   # Y方向 = long
                else:
                    surface_width = surface_bbox['long']   # X方向 = long
                    surface_depth = surface_bbox['short']  # Y方向 = short
                
                surface_height = desktop_layout.get('surface_dimensions', {}).get('height', 0.8)
            
            # 计算 surface 的左前角在房间中的位置
            surface_center_x = surface_position['x']
            surface_center_y = surface_position['y']
            
            surface_front_left_x = surface_center_x - surface_width / 2
            surface_front_left_y = surface_center_y - surface_depth / 2
            
            logger.info(f"{surface_name} at room position: ({surface_center_x:.2f}, {surface_center_y:.2f})")
            logger.info(f"{surface_name} front-left corner at: ({surface_front_left_x:.2f}, {surface_front_left_y:.2f}), height: {surface_height:.2f}")
            
            # 添加 desktop 资产（转换坐标）
            for item in desktop_layout.get('desktop_layout', []):
                name = item['name']
                local_pos = item['position']  # work surface 局部坐标
                rot = item.get('rotation_deg', {'x': 0, 'y': 0, 'z': 0})
                
                # 获取资产信息
                asset_info = self.get_asset_info(name)
                asset_id = asset_info['id'] if asset_info else name
                initial_location = asset_info['initial_location'] if asset_info else 'ExperimentalPlatform'
                
                # 转换为房间全局坐标
                room_x = surface_front_left_x + local_pos['x']
                room_y = surface_front_left_y + local_pos['y']
                room_z = surface_height  # 使用 work surface 高度
                
                objects.append({
                    "id": asset_id,
                    "position": {
                        "x": room_x,
                        "y": room_y,
                        "z": room_z
                    },
                    "rotation": {
                        "x": rot['x'],
                        "y": rot['y'],
                        "z": rot['z']
                    },
                    "initial_location": initial_location
                })
                total_desktop_items += 1
        
        # 获取 room 尺寸
        room_asset = None
        for item in room_layout['room_layout']:
            if item['name'] == 'LaboratoryRoom':
                room_info = self.get_asset_info('LaboratoryRoom', 'room_asset')
                if room_info:
                    room_asset = room_info
                    break
        
        if room_asset:
            room_bbox = room_asset['geometry']['bbox']
            room_size = {
                "w": room_bbox['short'],
                "d": room_bbox['long'],
                "h": room_bbox['height']
            }
        else:
            # 默认值
            room_size = {"w": 8.59, "d": 8.94, "h": 3.67}
        
        # 构建最终输出
        final_layout = {
            "query": experiment_name,
            "coordinate_system": "isaac_sim",
            "coordinate_note": "Isaac Sim standard: Z-up, X-right, Y-forward. Rotations around Z-axis.",
            "note": "Reconstructed from intermediate layout files - No LLM generation",
            "room_size": room_size,
            "objects": objects
        }
        
        logger.info(f"Created final layout with {len(objects)} objects ({len(room_layout['room_layout'])} room + {total_desktop_items} desktop)")
        
        return final_layout


def main():
    parser = argparse.ArgumentParser(
        description='Reconstruct Isaac Sim layout from intermediate files'
    )
    parser.add_argument(
        '--layout-dir',
        type=str,
        required=True,
        help='Directory containing intermediate layout files (*_room.json, *_layout.json)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output file path (default: auto-generate in layout-dir)'
    )
    parser.add_argument(
        '--asset-library',
        type=str,
        default='Table/Lablayout/assets_annotated.json',
        help='Path to assets_annotated.json (optional)'
    )
    parser.add_argument(
        '--batch',
        action='store_true',
        help='Batch mode: process all subdirectories in layout-dir'
    )
    
    args = parser.parse_args()
    
    # 初始化重建器
    reconstructor = LayoutReconstructor(asset_library_path=args.asset_library)
    
    layout_dir = Path(args.layout_dir)
    
    if args.batch:
        # 批量处理模式
        logger.info(f"Batch mode: processing all subdirectories in {layout_dir}")
        
        processed = 0
        failed = 0
        
        for subdir in layout_dir.iterdir():
            if not subdir.is_dir():
                continue
            
            # 检查是否包含布局文件
            has_room = any(subdir.glob("*_room.json"))
            if not has_room:
                continue
            
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {subdir.name}")
            logger.info(f"{'='*60}")
            
            try:
                output_path = Path(args.output) if args.output else None
                reconstructor.reconstruct(subdir, output_path)
                processed += 1
            except Exception as e:
                logger.error(f"Failed to process {subdir.name}: {e}")
                failed += 1
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Batch processing completed:")
        logger.info(f"  Processed: {processed}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"{'='*60}")
    else:
        # 单个目录处理
        if not layout_dir.is_dir():
            logger.error(f"Layout directory not found: {layout_dir}")
            return 1
        
        try:
            output_path = Path(args.output) if args.output else None
            reconstructor.reconstruct(layout_dir, output_path)
        except Exception as e:
            logger.error(f"Reconstruction failed: {e}", exc_info=True)
            return 1
    
    return 0


if __name__ == '__main__':
    exit(main())

