"""
资产加载器
从assets_annotated.json加载资产信息（bbox等）
"""

import json
from typing import Dict, Optional


class AssetLoader:
    """资产数据库加载器"""
    
    def __init__(self, asset_db_path: str):
        """
        初始化资产加载器
        
        Args:
            asset_db_path: assets_annotated.json文件路径
        """
        self.asset_db_path = asset_db_path
        self.asset_db = self._load_asset_db()
    
    def _load_asset_db(self) -> Dict:
        """加载assets_annotated.json"""
        try:
            with open(self.asset_db_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise RuntimeError(f"无法加载assets_annotated.json: {e}")
    
    def get_asset_info(self, asset_id: str) -> Optional[Dict]:
        """
        获取资产信息
        
        Args:
            asset_id: 资产ID（例如："Beaker"、"Beaker_1"、"FumeHood"、"LabBench"）
        
        Returns:
            asset_info: 包含id, name, type, geometry等信息的字典
        """
        assets_list = self.asset_db.get('assets', [])
        
        # 直接通过id或name匹配
        for asset in assets_list:
            if asset.get('id') == asset_id or asset.get('name') == asset_id:
                return asset
        
        # 尝试去掉数字后缀（Beaker_1 -> Beaker, RoundBottomFlask_2 -> RoundBottomFlask）
        if '_' in asset_id:
            # 分割并检查最后一部分是否为数字
            parts = asset_id.rsplit('_', 1)
            if len(parts) == 2 and parts[1].isdigit():
                base_id = parts[0]
                # 用base_id重新查找
                for asset in assets_list:
                    if asset.get('id') == base_id or asset.get('name') == base_id:
                        return asset
        
        # 尝试大小写不敏感匹配
        asset_id_lower = asset_id.lower()
        for asset in assets_list:
            if asset.get('id', '').lower() == asset_id_lower or asset.get('name', '').lower() == asset_id_lower:
                return asset
        
        # 尝试 snake_case 转 PascalCase 转换（例如 reagent_cabinet -> ReagentCabinet）
        def snake_to_pascal(s: str) -> str:
            return ''.join(word.capitalize() for word in s.split('_'))
        
        asset_id_pascal = snake_to_pascal(asset_id)
        for asset in assets_list:
            if asset.get('id') == asset_id_pascal or asset.get('name') == asset_id_pascal:
                return asset
        
        return None
    
    def get_asset_bbox(self, asset_id: str) -> Optional[Dict[str, float]]:
        """
        获取资产的包围盒（转换为内部格式）
        
        Args:
            asset_id: 资产ID
        
        Returns:
            bbox: {'x': short, 'y': long, 'z': height} (单位：米)
            
        Note:
            返回的 {x, y} 表示资产的 short/long 边，而非最终的 X/Y 方向占用尺寸。
            实际的 X/Y 方向占用尺寸需要通过 rotate_bbox() 函数根据旋转角度计算：
            - 0°/180°：X方向 = long, Y方向 = short
            - 90°/270°：X方向 = short, Y方向 = long
        """
        asset_info = self.get_asset_info(asset_id)
        if asset_info and 'geometry' in asset_info and 'bbox' in asset_info['geometry']:
            bbox_raw = asset_info['geometry']['bbox']
            
            # assets_annotated.json格式: {short, long, height}
            if 'short' in bbox_raw and 'long' in bbox_raw and 'height' in bbox_raw:
                return {
                    'x': bbox_raw['short'],   # 短边尺寸
                    'y': bbox_raw['long'],    # 长边尺寸
                    'z': bbox_raw['height']   # 高度
                }
            else:
                # 未知格式
                print(f"警告: {asset_id} 的bbox格式未知: {bbox_raw}")
                return {'x': 0.1, 'y': 0.1, 'z': 0.2}
        
        # 如果没有bbox信息，返回默认值
        print(f"警告: 未找到 {asset_id} 的bbox信息，使用默认值")
        return {'x': 0.1, 'y': 0.1, 'z': 0.2}
    
    def get_asset_type(self, asset_id: str) -> Optional[str]:
        """
        获取资产类型
        
        Args:
            asset_id: 资产ID
        
        Returns:
            asset_type: 'instrument', 'reagent', 'room_asset'等
        """
        asset_info = self.get_asset_info(asset_id)
        if asset_info:
            return asset_info.get('type')
        return None
    
    def is_reagent(self, asset_id: str) -> bool:
        """判断是否为试剂"""
        asset_type = self.get_asset_type(asset_id)
        return asset_type == 'reagent'
    
    def is_instrument(self, asset_id: str) -> bool:
        """判断是否为仪器"""
        asset_type = self.get_asset_type(asset_id)
        return asset_type == 'instrument'
    
    def is_glassware(self, asset_id: str) -> bool:
        """判断是否为玻璃器皿（用于C4约束）"""
        glassware_keywords = ['Beaker', 'Flask', 'Bottle', 'Tube', 'Burette', 'Pipette']
        return any(keyword in asset_id for keyword in glassware_keywords)
