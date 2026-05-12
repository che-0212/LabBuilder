"""
LLM Layout Engine V3
适应新的 protocol 格式和 assets_annotated.json 资产库

新特性：
1. 使用 assets_annotated.json 作为资产库
2. Protocol 中每个资产都有明确的 initial_location
3. Location（如 FumeHood）也是资产，从资产库获取
4. LLM 只对 initial_location="floor" 的资产进行二次选择
5. 支持新的朝向系统：front_direction 映射到旋转角度
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime

from labgen.layout_generator.prompts_v3 import (
    format_room_prompt_v3,
    format_desktop_prompt_v3
)
from utils.llm_config import LLMConfig, ModelAPI

logger = logging.getLogger(__name__)


class LLMLayoutEngineV3:
    """LLM驱动的布局生成引擎V3 - 适配新的 protocol 和资产库格式"""
    
    # 朝向映射：front_direction -> rotation_z
    FRONT_DIRECTION_TO_ROTATION = {
        (0, 1, 0): 0,      # 面向 Y 轴正方向
        (-1, 0, 0): 90,    # 面向 X 轴负方向
        (0, -1, 0): 180,   # 面向 Y 轴负方向
        (1, 0, 0): 270,    # 面向 X 轴正方向
    }
    
    def __init__(self, asset_library_path: str, llm_config: Dict = None):
        """
        Args:
            asset_library_path: assets_annotated.json 路径
            llm_config: LLM 配置
        """
        self.asset_library_path = asset_library_path
        self.assets_by_name = {}
        self.assets_by_type = {
            'room_asset': {},
            'instrument': {},
            'reagent': {}
        }
        
        # 加载资产库
        self._load_asset_library()
        
        # 初始化 LLM
        if llm_config is None:
            llm_config = {
                "model": "claude-sonnet-4-5-20250929",
                "temperature": 0.3,
                "max_tokens": 8192
            }
        self.llm_config = LLMConfig(**llm_config)
        self.llm_api = ModelAPI(self.llm_config)
        
        logger.info(f"Initialized LLM Layout Engine V3 with model: {self.llm_config.model}")
    
    def _load_asset_library(self):
        """加载 assets_annotated.json 资产库"""
        logger.info(f"Loading asset library from: {self.asset_library_path}")
        
        with open(self.asset_library_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for asset in data['assets']:
            name = asset['name']
            asset_type = asset.get('type', 'instrument')
            
            # 按名称索引（处理重复名称）
            if name not in self.assets_by_name:
                self.assets_by_name[name] = []
            self.assets_by_name[name].append(asset)
            
            # 按类型索引
            if asset_type not in self.assets_by_type:
                self.assets_by_type[asset_type] = {}
            if name not in self.assets_by_type[asset_type]:
                self.assets_by_type[asset_type][name] = []
            self.assets_by_type[asset_type][name].append(asset)
        
        logger.info(f"Loaded {len(self.assets_by_name)} unique asset names")
        logger.info(f"Asset types: {list(self.assets_by_type.keys())}")
        logger.info(f"Room assets: {len(self.assets_by_type.get('room_asset', {}))}")
    
    def get_asset_info(self, asset_name: str, asset_type: str = None) -> Optional[Dict]:
        """
        获取资产信息
        
        Args:
            asset_name: 资产名称
            asset_type: 资产类型（可选，用于消歧义）
            
        Returns:
            资产信息字典，如果不存在则返回 None
        """
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
    
    def _get_front_direction_rotation(self, front_direction: List[float]) -> float:
        """
        将 front_direction 转换为旋转角度
        
        Args:
            front_direction: [x, y, z] 朝向向量
            
        Returns:
            旋转角度（度）
        """
        # 转换为元组用于查找
        direction_tuple = tuple(int(x) for x in front_direction)
        
        # 查找映射
        rotation = self.FRONT_DIRECTION_TO_ROTATION.get(direction_tuple, 0)
        
        return rotation
    
    def generate_layout(
        self,
        protocol: Dict,
        output_dir: str
    ) -> Tuple[str, Dict]:
        """
        生成完整的布局
        
        新流程：
        1. 从 protocol 提取所有资产及其 initial_location
        2. 提取所有 initial_location="floor" 的资产让 LLM 选择
        3. 阶段1: 生成 room 布局（room + floor 资产）
        4. 阶段2: 生成桌面布局（根据 initial_location 分配）
        5. 阶段3: 合并为 Isaac Sim 格式
        
        Args:
            protocol: Protocol JSON
            output_dir: 输出目录
            
        Returns:
            (output_path, layout_data)
        """
        experiment_name = protocol['experiment_name']
        logger.info(f"Generating layout for: {experiment_name}")
        
        # 创建输出目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 移除所有文件系统不支持的字符
        safe_name = experiment_name.replace(' ', '_').replace('/', '-').replace(':', '-').replace('\\', '-')
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c in ('_', '-', '.'))[:50]
        output_subdir = Path(output_dir) / f"{safe_name}_{timestamp}"
        output_subdir.mkdir(parents=True, exist_ok=True)
        
        # 步骤1: 分析 protocol 资产和 location
        logger.info("Step 1: Analyzing protocol assets and locations...")
        asset_analysis = self._analyze_protocol_assets(protocol)
        
        # 保存分析结果
        analysis_path = output_subdir / f"{safe_name}_asset_analysis.json"
        with open(analysis_path, 'w', encoding='utf-8') as f:
            json.dump(asset_analysis, f, indent=2, ensure_ascii=False)
        logger.info(f"Asset analysis saved to: {analysis_path}")
        
        # 步骤2: 生成 room 布局（room + floor 资产）
        logger.info("Step 2: Generating room layout (room + floor assets)...")
        room_layout = self._generate_room_layout(protocol, asset_analysis)
        
        # 保存 room 布局
        room_path = output_subdir / f"{safe_name}_room.json"
        with open(room_path, 'w', encoding='utf-8') as f:
            json.dump(room_layout, f, indent=2, ensure_ascii=False)
        logger.info(f"Room layout saved to: {room_path}")
        
        # 步骤3: 为每个 work surface 生成桌面布局
        logger.info("Step 3: Generating desktop layouts...")
        desktop_layouts = self._generate_desktop_layouts(protocol, room_layout, asset_analysis)
        
        # 保存 desktop 布局
        for surface_name, layout in desktop_layouts.items():
            desktop_path = output_subdir / f"{safe_name}_{surface_name}_layout.json"
            with open(desktop_path, 'w', encoding='utf-8') as f:
                json.dump(layout, f, indent=2, ensure_ascii=False)
            logger.info(f"{surface_name} layout saved to: {desktop_path}")
        
        # 步骤4: 合并为 Isaac Sim 格式
        logger.info("Step 4: Creating final Isaac Sim layout...")
        final_layout = self._create_isaacsim_layout(room_layout, desktop_layouts, experiment_name)
        
        # 保存最终布局
        final_path = output_subdir / f"{safe_name}_room_isaacsim.json"
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(final_layout, f, indent=2, ensure_ascii=False)
        logger.info(f"Final layout saved to: {final_path}")
        
        return str(final_path), final_layout
    
    def _analyze_protocol_assets(self, protocol: Dict) -> Dict:
        """
        分析 protocol 中的资产
        
        Returns:
            {
                'protocol_assets': [...],  # protocol 中的所有资产（带 initial_location）
                'locations_as_assets': [...],  # location 作为资产（需要从资产库获取）
                'floor_assets_pool': [...],  # 资产库中所有 initial_location="floor" 的资产
                'required_locations': {...}  # 每个 location 需要放置的资产
            }
        """
        protocol_assets = protocol.get('assets', [])
        
        # 提取所有使用的 location (直接使用资产ID)
        locations = set()
        for asset in protocol_assets:
            # 如果没有initial_location，使用'desktop_unassigned'标记
            # 这样LLM可以自由选择将它们放在任何工作面上
            initial_loc = asset.get('initial_location', 'desktop_unassigned')
            locations.add(initial_loc)
        
        # 构建 protocol assets 名称到 initial_location 的映射
        # 用于检测哪些 procedure location 实际上是 desktop 级别的仪器
        protocol_asset_locations = {}
        for asset in protocol_assets:
            asset_name = asset.get('name', '')
            asset_initial_loc = asset.get('initial_location', 'desktop_unassigned')
            protocol_asset_locations[asset_name] = asset_initial_loc
        
        # 从步骤中提取 location
        for step in protocol.get('procedure', []):
            step_loc = step.get('location', '')
            if step_loc and step_loc != 'ReagentCabinet':
                # 检查这个 location 是否是 protocol assets 中的一个 desktop 仪器
                # 如果是，则不将其作为 floor 级别的 location
                if step_loc in protocol_asset_locations:
                    asset_loc = protocol_asset_locations[step_loc]
                    # 如果这个仪器的 initial_location 不是 floor，说明它是桌面设备
                    # 不应作为 room 级别的 location 处理
                    if asset_loc != 'floor':
                        logger.info(f"Skipping location '{step_loc}' as it's a desktop instrument (initial_location: {asset_loc})")
                        continue
                locations.add(step_loc)
        
        logger.info(f"Detected locations in protocol: {locations}")
        
        # Location 名称到资产名称的映射（处理大小写和格式不一致）
        location_to_asset_map = {
            'experimental_platform': 'ExperimentalPlatform',
            'ExperimentalPlatform': 'ExperimentalPlatform',
            'validation_platform': 'ValidationPlatform',
            'ValidationPlatform': 'ValidationPlatform',
            'reagent_cabinet': 'ReagentCabinet',
            'ReagentCabinet': 'ReagentCabinet',
            'FumeHood': 'FumeHood',
            'fume_hood': 'FumeHood',
            'GloveBox': 'GloveBox',
            'glove_box': 'GloveBox',
            'RotaryEvaporator': 'RotaryEvaporator',
            'GravityChromatographyColumn': 'GravityChromatographyColumn',
            'floor': None,  # floor 不是资产，跳过
        }
        
        # 获取 location 作为资产的信息
        locations_as_assets = []
        for loc in locations:
            # 跳过 floor（不是资产）
            if loc == 'floor':
                continue
            
            # 尝试映射到资产名称
            asset_name = location_to_asset_map.get(loc, loc)
            if asset_name is None:
                continue
            
            # 尝试查找资产（先尝试 room_asset，再尝试其他类型）
            asset_info = self.get_asset_info(asset_name, 'room_asset')
            if not asset_info:
                # 尝试不指定类型
                asset_info = self.get_asset_info(asset_name)
            
            if asset_info:
                locations_as_assets.append({
                    'location_name': loc,
                    'asset_name': asset_name,
                    'asset_info': asset_info
                })
            else:
                logger.warning(f"Location asset not found: {loc} (mapped to: {asset_name})")
        
        # 获取所有 floor 资产（用于 LLM 二次选择）
        # 排除已经确定的 location 资产
        required_location_asset_names = set(loc_data['asset_name'] for loc_data in locations_as_assets)
        
        # 按 initial_location 分组 protocol 资产
        required_locations = {}
        for asset in protocol_assets:
            # 如果没有initial_location，使用'desktop_unassigned'标记
            # 这样LLM可以自由选择将它们放在任何工作面上
            initial_loc = asset.get('initial_location', 'desktop_unassigned')
            if initial_loc not in required_locations:
                required_locations[initial_loc] = []
            required_locations[initial_loc].append(asset)
        
        # 获取 Protocol 中 initial_location == 'floor' 的资产，这些是必需的 floor 资产
        required_floor_assets = []
        for asset in required_locations.get('floor', []):
            asset_name = asset.get('name')
            # 从资产库获取资产信息
            asset_info = self.get_asset_info(asset_name)
            if asset_info:
                required_floor_assets.append({
                    'name': asset_name,
                    'asset_info': asset_info,
                    'is_required': True  # 标记为必需
                })
                logger.info(f"Found required floor asset from protocol: {asset_name}")
            else:
                logger.warning(f"Protocol asset {asset_name} with initial_location='floor' not found in asset library")
        
        floor_assets_pool = []
        # 添加必需的 floor 资产
        floor_assets_pool.extend(required_floor_assets)
        
        # 添加可选的 floor 资产（从资产库）
        for asset_name, assets in self.assets_by_type.get('room_asset', {}).items():
            # 跳过已经是必需 location 的资产
            if asset_name in required_location_asset_names:
                continue
            
            # 跳过已经在 required_floor_assets 中的资产
            if any(req_asset['name'] == asset_name for req_asset in required_floor_assets):
                continue
            
            for asset in assets:
                if asset.get('initial_location') == 'floor':
                    floor_assets_pool.append({
                        'name': asset_name,
                        'asset_info': asset,
                        'is_required': False  # 标记为可选
                    })
        
        logger.info(f"Found {len(required_floor_assets)} required floor assets from protocol")
        logger.info(f"Found {len(floor_assets_pool) - len(required_floor_assets)} optional floor assets (excluding required locations)")
        logger.info(f"Required location assets: {required_location_asset_names}")
        
        return {
            'protocol_assets': protocol_assets,
            'locations_as_assets': locations_as_assets,
            'floor_assets_pool': floor_assets_pool,
            'required_locations': required_locations,
            'all_locations': list(locations)
        }
    
    def _generate_room_layout(self, protocol: Dict, asset_analysis: Dict) -> Dict:
        """
        阶段1: 生成 room 布局
        
        包含：
        - LaboratoryRoom (必选)
        - protocol 中需要的 location 资产（如 LabBench, FumeHood 等）
        - LLM 从 floor_assets_pool 中选择的额外资产（如 Chair, Shelf 等）
        """
        experiment_name = protocol['experiment_name']
        experiment_description = protocol.get('experiment_description', '')
        
        # 提取安全警告和化学约束
        safety_warnings = protocol.get('safety_warnings', [])
        # 优先使用LLM生成的约束
        chemical_constraints = protocol.get('llm_generated_constraints') or protocol.get('chemical_constraints', [])
        
        # 生成 prompt
        prompt = format_room_prompt_v3(
            experiment_name=experiment_name,
            experiment_description=experiment_description,
            required_locations=asset_analysis['locations_as_assets'],
            floor_assets_pool=asset_analysis['floor_assets_pool'],
            safety_warnings=safety_warnings,
            chemical_constraints=chemical_constraints
        )
        
        # 调用 LLM（使用 system message 明确学术研究上下文）
        logger.info("Calling LLM for room layout generation...")
        system_prompt = "You are assisting with an academic chemistry laboratory layout design task. All chemical names and experimental procedures are for legitimate scientific research and educational purposes only."
        response = self.llm_api.call_with_system(system_prompt, prompt)
        
        # 解析响应
        room_layout = self._parse_llm_json_response(response)
        
        # 验证
        self._validate_room_layout(room_layout, asset_analysis)
        
        return room_layout
    
    def _generate_desktop_layouts(
        self,
        protocol: Dict,
        room_layout: Dict,
        asset_analysis: Dict
    ) -> Dict:
        """
        阶段2: 为每个 work surface 生成桌面布局
        
        根据 protocol 中资产的 initial_location 分配到对应的 work surface
        """
        layouts = {}
        
        # 获取 room 中的 work surfaces 信息
        work_surfaces = self._extract_work_surfaces(room_layout)
        
        # 按 initial_location 分组处理
        required_locations = asset_analysis['required_locations']
        
        # Location 名称到 surface 资产名称的映射
        location_to_surface_map = {
            'experimental_platform': 'ExperimentalPlatform',
            'ExperimentalPlatform': 'ExperimentalPlatform',
            'validation_platform': 'ValidationPlatform',
            'ValidationPlatform': 'ValidationPlatform',
            'reagent_cabinet': 'ReagentCabinet',
            'ReagentCabinet': 'ReagentCabinet',
            'FumeHood': 'FumeHood',
            'fume_hood': 'FumeHood',
            'GloveBox': 'GloveBox',
            'glove_box': 'GloveBox',
            'RotaryEvaporator': 'RotaryEvaporator',
            'GravityChromatographyColumn': 'GravityChromatographyColumn',
        }
        
        for location_name, assets in required_locations.items():
            # 跳过 floor（这些不需要桌面布局）
            if location_name in ['floor']:
                continue
            
            # 处理 desktop_unassigned：让 LLM 自由选择工作面
            if location_name == 'desktop_unassigned':
                logger.info(f"Found {len(assets)} desktop_unassigned assets, delegating to LLM for surface assignment...")
                # 对于 desktop_unassigned，LLM 会自行决定将资产分配到哪个工作面
                # 我们为所有可用的工作面生成一个统一的布局请求
                # LLM 会在响应中为每个资产指定 surface
                assigned_layouts = self._generate_unassigned_desktop_layouts(
                    protocol=protocol,
                    assets=assets,
                    work_surfaces=work_surfaces
                )
                # 合并生成的布局
                layouts.update(assigned_layouts)
                continue
            
            # 映射 location 名称到 surface 资产名称
            surface_name = location_to_surface_map.get(location_name, location_name)
            
            # 检查该 surface 是否在 room 布局中
            if surface_name not in work_surfaces:
                logger.warning(f"Surface {surface_name} (from location {location_name}) not found in room layout, skipping")
                continue
            
            surface_info = work_surfaces[surface_name]
            
            # 获取 surface 资产信息
            surface_asset_info = self.get_asset_info(surface_name, 'room_asset')
            if not surface_asset_info:
                logger.warning(f"Surface asset info not found: {surface_name}")
                continue
            
            # 获取 surface 的尺寸和旋转
            surface_bbox = surface_asset_info['geometry']['bbox']
            surface_rotation_z = surface_info.get('rotation', {}).get('z', 0)
            
            # 根据旋转计算有效宽度和深度（修正后的正确逻辑）
            # 0°/180°：长边平行于X轴 → width(X方向) = long, depth(Y方向) = short
            # 90°/270°：长边平行于Y轴 → width(X方向) = short, depth(Y方向) = long
            if surface_rotation_z in [90, 270, -90, -270]:
                surface_width = surface_bbox['short']  # X方向 = short
                surface_depth = surface_bbox['long']   # Y方向 = long
            else:
                surface_width = surface_bbox['long']   # X方向 = long
                surface_depth = surface_bbox['short']  # Y方向 = short
            
            surface_height = surface_bbox['height']
            
            logger.info(f"Generating layout for {surface_name} (location: {location_name})...")
            logger.info(f"  Surface dimensions: {surface_width:.2f}m × {surface_depth:.2f}m × {surface_height:.2f}m")
            logger.info(f"  Assets to place: {len(assets)}")
            
            # 获取资产的详细信息
            assets_with_info = []
            for asset in assets:
                asset_name = asset['name']
                asset_type = asset['type']
                asset_info = self.get_asset_info(asset_name, asset_type)
                if asset_info:
                    assets_with_info.append({
                        'protocol_asset': asset,
                        'asset_info': asset_info
                    })
                else:
                    logger.warning(f"Asset info not found: {asset_name} ({asset_type})")
            
            # 生成 prompt
            prompt = format_desktop_prompt_v3(
                experiment_name=protocol['experiment_name'],
                experiment_description=protocol.get('experiment_description', ''),
                surface_name=surface_name,
                surface_width=surface_width,
                surface_depth=surface_depth,
                surface_height=surface_height,
                assets=assets_with_info,
                chemical_constraints=protocol.get('llm_generated_constraints') or protocol.get('chemical_constraints', []),
                procedure=protocol.get('procedure', [])
            )
            
            # 调用 LLM（使用 system message 明确学术研究上下文）
            logger.info(f"Calling LLM for {surface_name} layout...")
            system_prompt = "You are assisting with an academic chemistry laboratory layout design task. All chemical names and experimental procedures are for legitimate scientific research and educational purposes only."
            response = self.llm_api.call_with_system(system_prompt, prompt)
            
            # 解析响应
            layout = self._parse_llm_json_response(response)
            
            # 验证
            self._validate_desktop_layout(layout, assets, surface_name)
            
            # 添加 surface 信息
            layout['surface_type'] = surface_name
            layout['surface_dimensions'] = {
                'width': surface_width,
                'depth': surface_depth,
                'height': surface_height
            }
            
            layouts[surface_name] = layout
        
        return layouts
    
    def _generate_unassigned_desktop_layouts(
        self,
        protocol: Dict,
        assets: List[Dict],
        work_surfaces: Dict
    ) -> Dict:
        """
        为 desktop_unassigned 资产生成布局
        LLM 会自行决定将每个资产分配到哪个工作面
        
        Returns:
            Dict[surface_name, layout_data]
        """
        logger.info("Generating layouts for desktop_unassigned assets...")
        
        # 获取所有可用工作面的信息
        available_surfaces = []
        for surface_name, surface_info in work_surfaces.items():
            surface_asset_info = self.get_asset_info(surface_name, 'room_asset')
            if surface_asset_info:
                available_surfaces.append({
                    'name': surface_name,
                    'bbox': surface_asset_info['geometry']['bbox'],
                    'position': surface_info['position']
                })
        
        # 准备资产信息
        assets_with_info = []
        for asset in assets:
            asset_name = asset['name']
            asset_type = asset['type']
            asset_info = self.get_asset_info(asset_name, asset_type)
            if asset_info:
                assets_with_info.append({
                    'protocol_asset': asset,
                    'asset_info': asset_info
                })
            else:
                logger.warning(f"Asset info not found: {asset_name} ({asset_type})")
        
        # 调用 LLM 进行智能分配和布局
        # LLM 会返回每个工作面的布局
        from labgen.layout_generator.prompts_v3 import format_unassigned_desktop_prompt_v3
        
        prompt = format_unassigned_desktop_prompt_v3(
            experiment_name=protocol['experiment_name'],
            experiment_description=protocol.get('experiment_description', ''),
            assets=assets_with_info,
            available_surfaces=available_surfaces,
            procedure=protocol.get('procedure', [])
        )
        
        try:
            logger.info("Calling LLM for unassigned desktop layout...")
            system_prompt = "You are assisting with an academic chemistry laboratory layout design task. All chemical names and experimental procedures are for legitimate scientific research and educational purposes only."
            response = self.llm_api.call_with_system(system_prompt, prompt)
            
            # 解析 LLM 响应
            # 期望格式：{"surface_name": {"desktop_layout": [...], "surface_type": "...", ...}, ...}
            layouts = self._parse_llm_json_response(response)
            
            logger.info(f"LLM assigned assets to {len(layouts)} surfaces")
            return layouts
            
        except Exception as e:
            logger.error(f"Failed to generate unassigned desktop layouts: {e}")
            # 失败时，默认将所有资产放在 ExperimentalPlatform 上
            logger.warning("Falling back to ExperimentalPlatform for all assets")
            return self._fallback_to_experimental_platform(protocol, assets, work_surfaces)
    
    def _fallback_to_experimental_platform(
        self,
        protocol: Dict,
        assets: List[Dict],
        work_surfaces: Dict
    ) -> Dict:
        """
        当 LLM 分配失败时的后备方案：将所有资产放在 ExperimentalPlatform 上
        """
        if 'ExperimentalPlatform' not in work_surfaces:
            logger.error("ExperimentalPlatform not found in work surfaces!")
            return {}
        
        surface_info = work_surfaces['ExperimentalPlatform']
        surface_asset_info = self.get_asset_info('ExperimentalPlatform', 'room_asset')
        
        if not surface_asset_info:
            logger.error("ExperimentalPlatform asset info not found!")
            return {}
        
        # 生成 ExperimentalPlatform 的布局
        surface_bbox = surface_asset_info['geometry']['bbox']
        surface_rotation_z = surface_info.get('rotation', {}).get('z', 0)
        
        if surface_rotation_z in [90, 270, -90, -270]:
            surface_width = surface_bbox['short']
            surface_depth = surface_bbox['long']
        else:
            surface_width = surface_bbox['long']
            surface_depth = surface_bbox['short']
        
        surface_height = surface_bbox['height']
        
        # 获取资产详细信息
        assets_with_info = []
        for asset in assets:
            asset_name = asset['name']
            asset_type = asset['type']
            asset_info = self.get_asset_info(asset_name, asset_type)
            if asset_info:
                assets_with_info.append({
                    'protocol_asset': asset,
                    'asset_info': asset_info
                })
        
        # 生成 prompt
        from labgen.layout_generator.prompts_v3 import format_desktop_prompt_v3
        
        prompt = format_desktop_prompt_v3(
            experiment_name=protocol['experiment_name'],
            experiment_description=protocol.get('experiment_description', ''),
            surface_name='ExperimentalPlatform',
            surface_width=surface_width,
            surface_depth=surface_depth,
            surface_height=surface_height,
            assets=assets_with_info,
            chemical_constraints=protocol.get('llm_generated_constraints') or protocol.get('chemical_constraints', []),
            procedure=protocol.get('procedure', [])
        )
        
        try:
            logger.info("Calling LLM for ExperimentalPlatform fallback layout...")
            system_prompt = "You are assisting with an academic chemistry laboratory layout design task. All chemical names and experimental procedures are for legitimate scientific research and educational purposes only."
            response = self.llm_api.call_with_system(system_prompt, prompt)
            
            layout_data = self._parse_llm_json_response(response)
            layout_data['surface_type'] = 'ExperimentalPlatform'
            layout_data['surface_dimensions'] = {
                'width': surface_width,
                'depth': surface_depth,
                'height': surface_height
            }
            return {'ExperimentalPlatform': layout_data}
            
        except Exception as e:
            logger.error(f"Fallback also failed: {e}")
            return {}
    
    def _extract_work_surfaces(self, room_layout: Dict) -> Dict:
        """从 room 布局中提取 work surfaces 信息"""
        surfaces = {}
        
        # Work surface 名称 - 所有可以放置桌面物品的工作台面
        work_surface_names = [
            'LabBench', 
            'ValidationPlatform', 
            'ExperimentalPlatform',  # 实验台
            'FumeHood', 
            'GloveBox', 
            'ReagentCabinet',
            'Cabinet',
            'Shelf'
        ]
        
        for item in room_layout.get('room_layout', []):
            name = item['name']
            if name in work_surface_names:
                surfaces[name] = {
                    'position': item['position'],
                    'rotation': item.get('rotation_deg', {'x': 0, 'y': 0, 'z': 0})
                }
        
        logger.info(f"Found work surfaces: {list(surfaces.keys())}")
        
        return surfaces
    
    def _normalize_surface_name_for_location(self, surface_name: str) -> str:
        """
        将表面名称规范化为 initial_location 格式（snake_case）
        与资产库中的 initial_location 格式保持一致
        """
        # 常见工作表面的映射
        name_mapping = {
            'ExperimentalPlatform': 'experimental_platform',
            'ValidationPlatform': 'validation_platform',
            'ReagentCabinet': 'reagent_cabinet',
            'FumeHood': 'FumeHood',  # 保持原样
            'LabBench': 'LabBench',  # 保持原样
            'LaboratoryWorkbench': 'LabBench',  # 别名
            'GloveBox': 'GloveBox',  # 保持原样
        }
        
        return name_mapping.get(surface_name, surface_name.lower().replace(' ', '_'))
    
    def _create_isaacsim_layout(
        self,
        room_layout: Dict,
        desktop_layouts: Dict,
        experiment_name: str
    ) -> Dict:
        """合并 room 和 desktop 布局，生成 Isaac Sim 格式"""
        
        # Location 现在直接使用资产ID，不需要映射
        objects = []
        total_desktop_items = 0
        
        # 添加 room 资产
        for item in room_layout['room_layout']:
            name = item['name']
            pos = item['position']
            rot = item['rotation_deg']
            
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
                logger.warning(f"Surface asset info not found: {surface_name}")
                continue
            
            surface_bbox = surface_asset_info['geometry']['bbox']
            
            # 根据旋转计算有效的宽度和深度（修正后的正确逻辑）
            # 0°/180°：长边平行于X轴 → width(X方向) = long, depth(Y方向) = short
            # 90°/270°：长边平行于Y轴 → width(X方向) = short, depth(Y方向) = long
            if surface_rotation_z in [90, 270, -90, -270]:
                surface_width = surface_bbox['short']  # X方向 = short
                surface_depth = surface_bbox['long']   # Y方向 = long
            else:
                surface_width = surface_bbox['long']   # X方向 = long
                surface_depth = surface_bbox['short']  # Y方向 = short
            
            # 计算 surface 的左前角在房间中的位置
            surface_center_x = surface_position['x']
            surface_center_y = surface_position['y']
            
            surface_front_left_x = surface_center_x - surface_width / 2
            surface_front_left_y = surface_center_y - surface_depth / 2
            
            surface_height = desktop_layout.get('surface_dimensions', {}).get('height', 0.8)
            
            logger.info(f"{surface_name} at room position: ({surface_center_x:.2f}, {surface_center_y:.2f})")
            logger.info(f"{surface_name} front-left corner at: ({surface_front_left_x:.2f}, {surface_front_left_y:.2f}), height: {surface_height:.2f}")
            
            # 添加 desktop 资产（转换坐标）
            for item in desktop_layout.get('desktop_layout', []):
                name = item['name']
                local_pos = item['position']  # work surface 局部坐标
                rot = item['rotation_deg']
                
                # 获取资产信息
                asset_info = self.get_asset_info(name)
                asset_id = asset_info['id'] if asset_info else name
                
                # 使用实际放置的表面名称（规范化为snake_case格式）
                initial_location = self._normalize_surface_name_for_location(surface_name)
                
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
            "note": "Generated by LLM Layout Engine V3 - Adapted for new protocol format and assets_annotated.json",
            "room_size": room_size,
            "objects": objects
        }
        
        logger.info(f"Created final layout with {len(objects)} objects ({len(room_layout['room_layout'])} room + {total_desktop_items} desktop)")
        
        return final_layout
    
    def _parse_llm_json_response(self, response: str) -> Dict:
        """解析 LLM 返回的 JSON"""
        response = response.strip()
        if response.startswith('```json'):
            response = response[7:]
        elif response.startswith('```'):
            response = response[3:]
        if response.endswith('```'):
            response = response[:-3]
        response = response.strip()
        
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.warning(f"Initial JSON parse failed: {e}, trying to extract first JSON object...")
            
            try:
                decoder = json.JSONDecoder()
                obj, idx = decoder.raw_decode(response)
                
                remaining = response[idx:].strip()
                if remaining:
                    logger.warning(f"Extra content after JSON (ignored): {remaining[:200]}...")
                
                return obj
            except Exception as e2:
                logger.error(f"Failed to extract JSON object: {e2}")
                logger.error(f"Response content: {response[:1000]}...")
                raise ValueError(f"Cannot parse LLM response as JSON: {e}")
    
    def _validate_room_layout(self, layout: Dict, asset_analysis: Dict):
        """验证 room 布局"""
        if 'room_layout' not in layout:
            raise ValueError("Missing 'room_layout' in response")
        
        room_items = layout['room_layout']
        names = [item['name'] for item in room_items]
        
        # 检查必选项
        if 'LaboratoryRoom' not in names:
            logger.warning("LaboratoryRoom not found in layout")
        
        # 检查所有必需的 location 资产是否都存在
        required_location_names = [loc['asset_name'] for loc in asset_analysis['locations_as_assets']]
        for req_name in required_location_names:
            if req_name not in names:
                logger.warning(f"Required location asset missing: {req_name}")
        
        # 检查位置和旋转
        for item in room_items:
            if 'position' not in item or 'rotation_deg' not in item:
                raise ValueError(f"Item {item.get('name')} missing position or rotation")
            
            pos = item['position']
            if not all(k in pos for k in ['x', 'y', 'z']):
                raise ValueError(f"Item {item.get('name')} position incomplete")
        
        logger.info(f"Room layout validation passed: {len(room_items)} items")
    
    def _validate_desktop_layout(self, layout: Dict, protocol_assets: List[Dict], surface_name: str):
        """验证 desktop 布局"""
        if 'desktop_layout' not in layout:
            raise ValueError(f"Missing 'desktop_layout' in {surface_name} response")
        
        desktop_items = layout['desktop_layout']
        placed_names = [item['name'] for item in desktop_items]
        required_names = [asset['name'] for asset in protocol_assets]
        
        # 检查是否所有资产都已放置（允许重复）
        placed_counts = {}
        for name in placed_names:
            placed_counts[name] = placed_counts.get(name, 0) + 1
        
        required_counts = {}
        for asset in protocol_assets:
            name = asset['name']
            quantity = asset.get('quantity', 1)
            required_counts[name] = required_counts.get(name, 0) + quantity
        
        for name, required_qty in required_counts.items():
            placed_qty = placed_counts.get(name, 0)
            if placed_qty < required_qty:
                raise ValueError(f"Missing {required_qty - placed_qty} instances of {name} in {surface_name} layout")
        
        # 检查坐标
        for item in desktop_items:
            if 'position' not in item or 'rotation_deg' not in item:
                raise ValueError(f"Item {item.get('name')} missing position or rotation")
            
            pos = item['position']
            if not all(k in pos for k in ['x', 'y', 'z']):
                raise ValueError(f"Item {item.get('name')} position incomplete")
        
        logger.info(f"{surface_name} layout validation passed: {len(desktop_items)} items")
