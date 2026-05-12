"""
布局自动修正器
使用精确的几何规则修正贴墙资产和边界违规
"""

import json
import logging
from typing import Dict, List, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class WallMountedAssetFixer:
    """贴墙资产自动修正器"""
    
    # 必须贴墙的资产
    WALL_MOUNTED_ASSETS = ["FumeHood", "ReagentCabinet", "Shelf", "Refrigerator"]
    
    # 房间边界（20cm墙厚）
    ROOM_BOUNDS = {
        'x_min': 0.2,
        'x_max': 8.39,
        'y_min': 0.2,
        'y_max': 8.74
    }
    
    def __init__(self, asset_library: Dict):
        """
        初始化修正器
        
        Args:
            asset_library: assets_annotated.json 的内容
        """
        self.asset_library = asset_library
        self.assets_dict = {asset['id']: asset for asset in asset_library.get('assets', [])}
    
    def get_bbox(self, asset_id: str) -> Optional[Dict]:
        """获取资产的 bbox"""
        asset = self.assets_dict.get(asset_id)
        if not asset:
            return None
        
        geometry = asset.get('geometry', {})
        bbox = geometry.get('bbox', {})
        
        if bbox and 'short' in bbox and 'long' in bbox:
            return {
                'short': bbox['short'],
                'long': bbox['long'],
                'height': bbox.get('height', 0)
            }
        return None
    
    def detect_nearest_wall(self, pos: Dict) -> str:
        """
        检测最近的墙面
        
        Args:
            pos: {'x': float, 'y': float, 'z': float}
        
        Returns:
            'west', 'east', 'south', 'north'
        """
        x, y = pos['x'], pos['y']
        
        distances = {
            'west': abs(x - self.ROOM_BOUNDS['x_min']),
            'east': abs(x - self.ROOM_BOUNDS['x_max']),
            'south': abs(y - self.ROOM_BOUNDS['y_min']),
            'north': abs(y - self.ROOM_BOUNDS['y_max'])
        }
        
        return min(distances, key=distances.get)
    
    def calculate_wall_position(
        self, 
        wall: str, 
        bbox: Dict, 
        current_pos: Dict
    ) -> Dict:
        """
        计算正确的贴墙位置和旋转
        
        Args:
            wall: 'west', 'east', 'south', 'north'
            bbox: {'short': float, 'long': float, 'height': float}
            current_pos: 当前位置（用于计算沿墙的坐标）
        
        Returns:
            {'position': {'x': float, 'y': float}, 'rotation_z': float}
        """
        short = bbox['short']
        long = bbox['long']
        
        # 修正后的旋转规则：
        # - 0°/180°：长边平行于X轴 → X方向 = long, Y方向 = short
        # - 90°/270°：长边平行于Y轴 → X方向 = short, Y方向 = long
        #
        # 贴墙要求：短边垂直于墙，长边平行于墙
        # - 西墙/东墙（垂直）：长边沿Y轴 → 用 90°/270° → X=short, Y=long → x需考虑short
        # - 南墙/北墙（水平）：长边沿X轴 → 用 0°/180° → X=long, Y=short → y需考虑short
        
        if wall == 'west':
            # 西墙：用 270°（面向+X），长边平行于Y轴 → X方向 = short
            return {
                'position': {
                    'x': self.ROOM_BOUNDS['x_min'] + short / 2,
                    'y': current_pos['y']
                },
                'rotation_z': 270.0
            }
        
        elif wall == 'east':
            # 东墙：用 90°（面向-X），长边平行于Y轴 → X方向 = short
            return {
                'position': {
                    'x': self.ROOM_BOUNDS['x_max'] - short / 2,
                    'y': current_pos['y']
                },
                'rotation_z': 90.0
            }
        
        elif wall == 'south':
            # 南墙：用 0°（面向+Y），长边平行于X轴 → Y方向 = short
            return {
                'position': {
                    'x': current_pos['x'],
                    'y': self.ROOM_BOUNDS['y_min'] + short / 2
                },
                'rotation_z': 0.0
            }
        
        elif wall == 'north':
            # 北墙：用 180°（面向-Y），长边平行于X轴 → Y方向 = short
            return {
                'position': {
                    'x': current_pos['x'],
                    'y': self.ROOM_BOUNDS['y_max'] - short / 2
                },
                'rotation_z': 180.0
            }
        
        return None
    
    def check_and_fix_boundaries(
        self, 
        obj: Dict, 
        bbox: Dict
    ) -> bool:
        """
        检查并修正边界违规
        
        Args:
            obj: 布局对象
            bbox: 资产的 bbox
        
        Returns:
            是否进行了修正
        """
        pos = obj['position']
        rot_z = obj['rotation']['z']
        
        # 计算旋转后的实际尺寸（修正后的正确逻辑）
        # 0°/180°：长边平行于X轴 → X=long, Y=short
        # 90°/270°：长边平行于Y轴 → X=short, Y=long
        if rot_z in [90, 270, -90, -270]:
            actual_x = bbox['short']
            actual_y = bbox['long']
        else:
            actual_x = bbox['long']
            actual_y = bbox['short']
        
        half_x = actual_x / 2
        half_y = actual_y / 2
        
        x_min = pos['x'] - half_x
        x_max = pos['x'] + half_x
        y_min = pos['y'] - half_y
        y_max = pos['y'] + half_y
        
        fixed = False
        
        # 检查并修正 X 边界
        if x_min < self.ROOM_BOUNDS['x_min']:
            pos['x'] = self.ROOM_BOUNDS['x_min'] + half_x + 0.01  # 1cm 安全距离
            fixed = True
            logger.info(f"修正 {obj['id']} X 下边界：{x_min:.3f} -> {pos['x']:.3f}")
        
        if x_max > self.ROOM_BOUNDS['x_max']:
            pos['x'] = self.ROOM_BOUNDS['x_max'] - half_x - 0.01
            fixed = True
            logger.info(f"修正 {obj['id']} X 上边界：{x_max:.3f} -> {pos['x']:.3f}")
        
        # 检查并修正 Y 边界
        if y_min < self.ROOM_BOUNDS['y_min']:
            pos['y'] = self.ROOM_BOUNDS['y_min'] + half_y + 0.01
            fixed = True
            logger.info(f"修正 {obj['id']} Y 下边界：{y_min:.3f} -> {pos['y']:.3f}")
        
        if y_max > self.ROOM_BOUNDS['y_max']:
            pos['y'] = self.ROOM_BOUNDS['y_max'] - half_y - 0.01
            fixed = True
            logger.info(f"修正 {obj['id']} Y 上边界：{y_max:.3f} -> {pos['y']:.3f}")
        
        return fixed
    
    def fix_layout(self, layout: Dict, fix_wall_mounted: bool = True) -> Tuple[Dict, int]:
        """
        自动修正布局
        
        Args:
            layout: 布局 JSON
            fix_wall_mounted: 是否修正贴墙资产
        
        Returns:
            (修正后的布局, 修正数量)
        """
        fix_count = 0
        
        for obj in layout.get('objects', []):
            asset_id = obj.get('id')
            initial_location = obj.get('initial_location')
            
            # 只处理地板物体
            if initial_location != 'floor':
                continue
            
            # 跳过房间本身
            if 'Room' in asset_id or 'room' in asset_id.lower():
                continue
            
            # 获取 bbox
            bbox = self.get_bbox(asset_id)
            if not bbox:
                logger.warning(f"无法获取 {asset_id} 的 bbox，跳过")
                continue
            
            # 1. 贴墙资产修正
            if fix_wall_mounted and asset_id in self.WALL_MOUNTED_ASSETS:
                pos = obj['position']
                wall = self.detect_nearest_wall(pos)
                
                corrected = self.calculate_wall_position(wall, bbox, pos)
                
                if corrected:
                    old_pos = (pos['x'], pos['y'])
                    old_rot = obj['rotation']['z']
                    
                    pos['x'] = corrected['position']['x']
                    pos['y'] = corrected['position']['y']
                    obj['rotation']['z'] = corrected['rotation_z']
                    
                    logger.info(
                        f"修正 {asset_id} 贴墙位置：{wall}墙 "
                        f"位置 ({old_pos[0]:.3f}, {old_pos[1]:.3f}) -> ({pos['x']:.3f}, {pos['y']:.3f}), "
                        f"旋转 {old_rot}° -> {corrected['rotation_z']}°"
                    )
                    fix_count += 1
            
            # 2. 边界检查与修正（所有地板物体）
            if self.check_and_fix_boundaries(obj, bbox):
                fix_count += 1
        
        logger.info(f"布局修正完成，共修正 {fix_count} 个资产")
        return layout, fix_count


def fix_layout_file(
    layout_path: Path, 
    asset_library_path: Path,
    output_path: Optional[Path] = None,
    fix_wall_mounted: bool = True
) -> Tuple[Dict, int]:
    """
    修正布局文件
    
    Args:
        layout_path: 布局文件路径
        asset_library_path: 资产库路径
        output_path: 输出路径（None 表示覆盖原文件）
        fix_wall_mounted: 是否修正贴墙资产
    
    Returns:
        (修正后的布局, 修正数量)
    """
    # 读取文件
    with layout_path.open('r', encoding='utf-8') as f:
        layout = json.load(f)
    
    with asset_library_path.open('r', encoding='utf-8') as f:
        asset_library = json.load(f)
    
    # 修正
    fixer = WallMountedAssetFixer(asset_library)
    layout, fix_count = fixer.fix_layout(layout, fix_wall_mounted=fix_wall_mounted)
    
    # 保存
    if output_path is None:
        output_path = layout_path
    
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(layout, f, indent=2, ensure_ascii=False)
    
    logger.info(f"修正后的布局已保存到：{output_path}")
    
    return layout, fix_count


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 示例用法
    import sys
    
    if len(sys.argv) < 2:
        print("用法：python layout_fixer.py <layout.json> [asset_library.json] [--no-wall]")
        sys.exit(1)
    
    layout_path = Path(sys.argv[1])
    asset_library_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("assets_annotated.json")
    fix_wall = "--no-wall" not in sys.argv
    
    layout, fix_count = fix_layout_file(layout_path, asset_library_path, fix_wall_mounted=fix_wall)
    
    print(f"\n✓ 修正完成！共修正 {fix_count} 个资产")
    print(f"  布局文件：{layout_path}")

