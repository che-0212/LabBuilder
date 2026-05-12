import json
import numpy as np
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端，适用于无GUI环境
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import Rectangle, Polygon
from pathlib import Path
import math
from PIL import Image, ImageDraw
from typing import Dict, List, Optional, Tuple
from heapq import heappush, heappop
from scipy import ndimage


class NavigationIterativeOptimizer:
    """导航迭代优化器 - 用于生成实验室布局的二维俯视图"""
    
    def __init__(self, layout_json_path, assets_json_path):
        """
        初始化优化器
        
        Args:
            layout_json_path: 布局JSON文件路径
            assets_json_path: 资产尺寸JSON文件路径
        """
        self.layout_json_path = layout_json_path
        self.assets_json_path = assets_json_path
        self.layout_data = None
        self.assets_data = None
        self.assets_dict = {}  # id -> asset info
        
    def load_data(self):
        """加载布局和资产数据"""
        print("正在加载数据...")
        with open(self.layout_json_path, 'r', encoding='utf-8') as f:
            self.layout_data = json.load(f)
        
        with open(self.assets_json_path, 'r', encoding='utf-8') as f:
            assets_data = json.load(f)
            self.assets_data = assets_data
            
        # 构建资产字典，方便快速查找
        if 'assets' in self.assets_data:
            for asset in self.assets_data['assets']:
                self.assets_dict[asset['id']] = asset
        print("数据加载完成")
    
    def _calculate_room_bounds(self):
        """
        计算房间的实际可用边界（扣除墙厚）
        
        Returns:
            (min_x, max_x, min_y, max_y) 或 None
        """
        if self.layout_data is None:
            return None
        
        # 墙厚
        WALL_THICKNESS = 0.20  # 20cm，与GeometryMetrics保持一致
        
        # 查找房间对象
        room_obj = None
        for obj in self.layout_data.get('objects', []):
            if obj.get('id') == 'LaboratoryRoom':
                room_obj = obj
                break
        
        if not room_obj:
            return None
        
        # 获取房间尺寸
        room_size = self.layout_data.get('room_size', {})
        if not room_size:
            return None
        
        room_w = room_size.get('w', 9.0)
        room_d = room_size.get('d', 9.0)
        
        # 获取房间位置
        room_pos = room_obj.get('position', {})
        cx = room_pos.get('x', 0)
        cy = room_pos.get('y', 0)
        
        # 计算边界（扣除墙厚）
        half_w = room_w / 2
        half_d = room_d / 2
        
        min_x = cx - half_w + WALL_THICKNESS
        max_x = cx + half_w - WALL_THICKNESS
        min_y = cy - half_d + WALL_THICKNESS
        max_y = cy + half_d - WALL_THICKNESS
        
        return (min_x, max_x, min_y, max_y)
    
    def get_object_size(self, object_id):
        """
        获取物体的尺寸信息
        
        Args:
            object_id: 物体ID
            
        Returns:
            (short, long, height) 或 None
        """
        if object_id in self.assets_dict:
            bbox = self.assets_dict[object_id]['geometry']['bbox']
            return bbox['short'], bbox['long'], bbox['height']
        return None
    
    def rotate_point(self, point, center, angle_deg):
        """
        绕中心点旋转点
        
        Args:
            point: (x, y) 点坐标
            center: (cx, cy) 中心点
            angle_deg: 旋转角度（度）
            
        Returns:
            旋转后的点 (x, y)
        """
        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        
        x, y = point[0] - center[0], point[1] - center[1]
        x_new = x * cos_a - y * sin_a
        y_new = x * sin_a + y * cos_a
        
        return x_new + center[0], y_new + center[1]
    
    def get_rotated_rectangle(self, center_x, center_y, width, length, rotation_z):
        """
        获取旋转后的矩形四个顶点
        
        Args:
            center_x, center_y: 中心点坐标
            width: 宽度（short短边）
            length: 长度（long长边）
            rotation_z: 绕Z轴旋转角度（度）
            
        Returns:
            四个顶点的列表 [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
        """
        # 根据用户说明：
        # 0度 = 面向Y轴正方向
        # 长边（long）平行X轴
        # 短边（short）平行Y轴
        
        # 注意：参数 width=short, length=long
        # 所以在0度时：
        # - length(long) 沿着 X轴
        # - width(short) 沿着 Y轴
        
        half_long = length / 2  # 长边的一半，沿X轴
        half_short = width / 2  # 短边的一半，沿Y轴
        
        # 初始矩形顶点：0度时面向+Y方向，长边沿X轴，短边沿Y轴
        # 顶点顺序：左下, 右下, 右上, 左上
        corners = [
            (-half_long, -half_short),  # 左下：X负，Y负
            (half_long, -half_short),   # 右下：X正，Y负
            (half_long, half_short),    # 右上：X正，Y正
            (-half_long, half_short)    # 左上：X负，Y正
        ]
        
        # 旋转每个顶点
        # Isaac Sim的旋转是逆时针（从Z轴正方向看下去）
        center = (center_x, center_y)
        rotated_corners = [self.rotate_point((center_x + x, center_y + y), center, rotation_z) 
                          for x, y in corners]
        
        return rotated_corners
    
    def generate_top_view(self, output_path, dpi=300, scale_factor=100):
        """
        生成二维俯视图
        
        Args:
            output_path: 输出PNG文件路径
            dpi: 图片分辨率（每英寸像素数）
            scale_factor: 缩放因子，控制每个像素代表的实际距离（像素/米）
        """
        print("正在生成俯视图...")
        if self.layout_data is None:
            self.load_data()
        
        room_size = self.layout_data['room_size']
        room_width = room_size['w']
        room_depth = room_size['d']
        
        # 计算图片尺寸（像素）
        img_width_px = int(room_width * scale_factor)
        img_height_px = int(room_depth * scale_factor)
        
        # 计算房间的实际边界
        # 房间中心位置
        room_center_x = self.layout_data['objects'][0]['position']['x']  # LaboratoryRoom的x
        room_center_y = self.layout_data['objects'][0]['position']['y']  # LaboratoryRoom的y
        
        # 计算房间左下角（原点）
        room_min_x = room_center_x - room_width / 2
        room_min_y = room_center_y - room_depth / 2
        room_max_x = room_center_x + room_width / 2
        room_max_y = room_center_y + room_depth / 2
        
        # 创建图形
        fig, ax = plt.subplots(figsize=(img_width_px/dpi, img_height_px/dpi), dpi=dpi)
        ax.set_xlim(room_min_x, room_max_x)
        ax.set_ylim(room_min_y, room_max_y)
        ax.set_aspect('equal')
        # Y轴从下到上递增，底部为0
        ax.set_xlabel('X (m)')
        ax.set_ylabel('Y (m)')
        ax.set_title('Laboratory Layout Top View')
        
        # 绘制坐标轴原点标记
        ax.plot(0, 0, 'ko', markersize=8, label='Origin (0,0)')
        ax.axhline(y=0, color='k', linestyle='--', linewidth=0.5, alpha=0.5)
        ax.axvline(x=0, color='k', linestyle='--', linewidth=0.5, alpha=0.5)
        
        # 绘制房间边界
        room_rect = Rectangle((room_min_x, room_min_y), room_width, room_depth, 
                             linewidth=2, edgecolor='black', facecolor='lightgray', alpha=0.3)
        ax.add_patch(room_rect)
        
        # 绘制每个物体
        for obj in self.layout_data['objects']:
            obj_id = obj['id']
            pos = obj['position']
            rot = obj['rotation']
            
            # 跳过房间本身
            if obj_id == 'LaboratoryRoom':
                continue
            
            # 获取物体尺寸
            size_info = self.get_object_size(obj_id)
            if size_info is None:
                # 如果没有找到尺寸信息，用默认小点表示
                ax.plot(pos['x'], pos['y'], 'ro', markersize=5)
                continue
            
            short, long_dim, height = size_info
            
            # 获取旋转角度
            # 已修正：函数内部正确处理了0度时长边沿X轴的情况
            rotation_z = rot.get('z', 0)
            
            # 计算旋转后的矩形顶点
            corners = self.get_rotated_rectangle(
                pos['x'], pos['y'], 
                short, long_dim, 
                rotation_z  # 直接使用rotation_z，不需要+90度补偿
            )
            
            # 绘制矩形
            polygon = Polygon(corners, closed=True, 
                            edgecolor='blue', facecolor='lightblue', 
                            alpha=0.6, linewidth=1)
            ax.add_patch(polygon)
            
            # 添加物体ID标签
            ax.text(pos['x'], pos['y'], obj_id, 
                   fontsize=6, ha='center', va='center',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))
        
        # 保存图片
        plt.tight_layout()
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight', format='png')
        plt.close()
        
        print(f"俯视图已保存到: {output_path}")
        print(f"图片尺寸: {img_width_px}x{img_height_px} 像素")
        print(f"分辨率: {dpi} DPI")
        print(f"每个像素代表: {1.0/scale_factor:.4f} 米")
    
    def generate_mask(self, output_path, scale_factor=100):
        """
        生成二值mask图用于导航判断
        
        Args:
            output_path: 输出PNG文件路径
            scale_factor: 缩放因子，控制每个像素代表的实际距离（像素/米）
        """
        print("正在生成mask图...")
        if self.layout_data is None:
            self.load_data()
        
        room_size = self.layout_data['room_size']
        room_width = room_size['w']
        room_depth = room_size['d']
        
        # 计算图片尺寸（像素）
        img_width_px = int(room_width * scale_factor)
        img_height_px = int(room_depth * scale_factor)
        
        # 计算房间的实际边界
        room_center_x = self.layout_data['objects'][0]['position']['x']
        room_center_y = self.layout_data['objects'][0]['position']['y']
        room_min_x = room_center_x - room_width / 2
        room_min_y = room_center_y - room_depth / 2
        
        # 创建mask数组，初始化为255（白色，可导航区域）
        mask = np.ones((img_height_px, img_width_px), dtype=np.uint8) * 255
        
        # 坐标转换函数：将世界坐标转换为像素坐标
        def world_to_pixel(wx, wy):
            px = int((wx - room_min_x) * scale_factor)
            py = int((wy - room_min_y) * scale_factor)
            # 注意：图像坐标系Y轴向下，需要翻转
            py = img_height_px - 1 - py
            return px, py
        
        # 绘制每个物体为障碍物（黑色，0）- 只绘制地面物体
        for obj in self.layout_data['objects']:
            obj_id = obj['id']
            pos = obj['position']
            rot = obj['rotation']
            
            # 跳过房间本身
            if obj_id == 'LaboratoryRoom':
                continue
            
            # 只绘制地面物体，桌面物体不会阻塞机器人导航
            initial_location = obj.get('initial_location', 'floor')
            if initial_location != 'floor':
                continue
            
            # 获取物体尺寸
            size_info = self.get_object_size(obj_id)
            if size_info is None:
                # 如果没有找到尺寸信息，用一个小点表示
                px, py = world_to_pixel(pos['x'], pos['y'])
                if 0 <= px < img_width_px and 0 <= py < img_height_px:
                    mask[py, px] = 0
                continue
            
            short, long_dim, height = size_info
            
            # 获取旋转角度
            rotation_z = rot.get('z', 0)
            
            # 计算旋转后的矩形顶点
            corners = self.get_rotated_rectangle(
                pos['x'], pos['y'], 
                short, long_dim,
                rotation_z
            )
            
            # 将世界坐标转换为像素坐标
            pixel_corners = [world_to_pixel(cx, cy) for cx, cy in corners]
            
            # 使用PIL绘制多边形
            img = Image.fromarray(mask)
            draw = ImageDraw.Draw(img)
            draw.polygon(pixel_corners, fill=0)  # 0表示障碍物（黑色）
            mask = np.array(img)
        
        # 保存mask图
        mask_img = Image.fromarray(mask, mode='L')
        mask_img.save(output_path)
        
        print(f"Mask图已保存到: {output_path}")
        print(f"图片尺寸: {img_width_px}x{img_height_px} 像素")
        print(f"每个像素代表: {1.0/scale_factor:.4f} 米")
        print(f"Mask值: 0=障碍物（黑色）, 255=可导航区域（白色）")
    
    @staticmethod
    def _norm(s: str) -> str:
        """规范化字符串：去除下划线/空格/横线，转小写"""
        if not s:
            return ""
        return str(s).lower().replace(" ", "").replace("-", "").replace("_", "")
    
    def build_location_mapping(self, protocol_data: dict) -> dict:
        """
        构建location到物体ID的映射
        
        Args:
            protocol_data: protocol JSON数据
            
        Returns:
            location -> object_id 映射字典
        """
        special_mapping = {
            "labbench": "ExperimentalPlatform",
            "bench": "ExperimentalPlatform",
            "experimental_platform": "ExperimentalPlatform",
            "hood": "FumeHood",
            "fumehood": "FumeHood",
            "validation_platform": "ValidationPlatform",
            "reagent_cabinet": "ReagentCabinet",
            "rotaryevaporator": "RotaryEvaporator"
        }
        
        locations = set()
        for step in protocol_data.get("procedure", []):
            loc = step.get("location")
            if loc:
                locations.add(loc)
        
        platform_ids = [obj.get("id", "") for obj in self.layout_data.get("objects", [])]
        
        result = {}
        for loc in locations:
            norm_loc = self._norm(loc)
            
            # 1. 先检查特殊映射
            if norm_loc in special_mapping:
                result[loc] = special_mapping[norm_loc]
                continue
            
            # 2. 规范化匹配
            matched = None
            for pid in platform_ids:
                if self._norm(pid) == norm_loc:
                    matched = pid
                    break
            
            # 3. 模糊匹配
            if not matched:
                for pid in platform_ids:
                    if self._norm(pid).startswith(norm_loc) or norm_loc.startswith(self._norm(pid)):
                        matched = pid
                        break
            
            result[loc] = matched if matched else loc
        
        return result
    
    def calculate_nav_target(self, obj: dict, offset_radius: float) -> Optional[dict]:
        """
        计算导航目标点，并自动检测和修正面向墙面的设备
        
        Args:
            obj: 物体对象
            offset_radius: 机器人半径
            
        Returns:
            包含目标点坐标的字典或None
        """
        obj_id = obj.get('id')
        size_info = self.get_object_size(obj_id)
        if size_info is None:
            return None
        
        short, long_dim, height = size_info
        pos = obj.get('position', {})
        rot = obj.get('rotation', {})
        
        cx = pos.get('x', 0)
        cy = pos.get('y', 0)
        rz_deg = rot.get('z', 0)
        
        # 机器人停靠距离
        hx = short / 2
        dist = hx + offset_radius + 0.2
        rad = math.radians(rz_deg)
        
        # 投影计算 (0deg=+Y, 270deg=+X)
        dx_raw = -dist * math.sin(rad)
        dy_raw = dist * math.cos(rad)
        
        tx = cx + dx_raw
        ty = cy + dy_raw
        
        # 检测操作点是否在房间外 - 如果是，建议旋转180°
        room_bounds = self._calculate_room_bounds()
        if room_bounds is not None:
            min_x, max_x, min_y, max_y = room_bounds
            
            # 检查操作点是否在房间外（带1cm容差）
            tolerance = 0.01
            if (tx < min_x - tolerance or tx > max_x + tolerance or 
                ty < min_y - tolerance or ty > max_y + tolerance):
                
                # 操作点在房间外！旋转180度后重新计算
                print(f"⚠️  {obj_id} 面向墙面（操作点在房间外: ({tx:.2f}, {ty:.2f})），建议旋转180°")
                
                # 旋转180度后的操作点
                rz_deg_flipped = (rz_deg + 180) % 360
                rad_flipped = math.radians(rz_deg_flipped)
                
                dx_flipped = -dist * math.sin(rad_flipped)
                dy_flipped = dist * math.cos(rad_flipped)
                
                tx_flipped = cx + dx_flipped
                ty_flipped = cy + dy_flipped
                
                # 检查翻转后的操作点是否在房间内
                if (min_x - tolerance <= tx_flipped <= max_x + tolerance and 
                    min_y - tolerance <= ty_flipped <= max_y + tolerance):
                    print(f"   ✓ 旋转后操作点在房间内: ({tx_flipped:.2f}, {ty_flipped:.2f})")
                    return {
                        'x': tx_flipped,
                        'y': ty_flipped,
                        'object_id': obj_id,
                        'needs_rotation': True,  # 标记需要旋转
                        'suggested_rotation': rz_deg_flipped
                    }
                else:
                    print(f"   ✗ 旋转后仍在房间外: ({tx_flipped:.2f}, {ty_flipped:.2f})")
        
        return {
            'x': tx,
            'y': ty,
            'object_id': obj_id,
            'needs_rotation': False
        }
    
    def get_nav_points_from_protocol(self, protocol_json_path: str, offset_radius: float = 0.6) -> List[dict]:
        """
        从protocol JSON提取导航点序列
        
        Args:
            protocol_json_path: protocol JSON文件路径
            offset_radius: 机器人半径
            
        Returns:
            导航点列表，每个元素包含(x, y, object_id, step_number)
        """
        with open(protocol_json_path, 'r', encoding='utf-8') as f:
            protocol_data = json.load(f)
        
        if self.layout_data is None:
            self.load_data()
        
        location_mapping = self.build_location_mapping(protocol_data)
        nav_points = []
        rotation_fixes = []  # 收集需要旋转的设备
        
        steps = protocol_data.get("procedure", [])
        for step in steps:
            step_num = step.get("step_number")
            loc = step.get("location")
            
            if not loc:
                continue
            
            matched_id = location_mapping.get(loc)
            if not matched_id:
                continue
            
            # 在布局中找到该对象实例
            target_obj = None
            for obj in self.layout_data.get("objects", []):
                if self._norm(obj.get("id", "")) == self._norm(matched_id):
                    target_obj = obj
                    break
            
            if target_obj:
                nav_target = self.calculate_nav_target(target_obj, offset_radius)
                if nav_target:
                    nav_points.append({
                        'x': nav_target['x'],
                        'y': nav_target['y'],
                        'object_id': nav_target['object_id'],
                        'step_number': step_num,
                        'location': loc
                    })
                    
                    # 记录需要旋转的设备
                    if nav_target.get('needs_rotation', False):
                        rotation_fixes.append({
                            'object_id': nav_target['object_id'],
                            'current_rotation': target_obj.get('rotation', {}).get('z', 0),
                            'suggested_rotation': nav_target['suggested_rotation'],
                            'step_number': step_num,
                            'location': loc
                        })
        
        # 存储旋转修复建议供后续使用
        self._rotation_fixes = rotation_fixes
        
        return nav_points
    
    def _dilate_mask_circular(self, mask: np.ndarray, radius: int) -> np.ndarray:
        """
        对mask图进行圆形膨胀操作，扩展障碍物
        
        Args:
            mask: 原始mask图 (255=可通行, 0=障碍)
            radius: 膨胀半径（像素）
            
        Returns:
            膨胀后的mask图 (255=可通行, 0=障碍)
        """
        if radius <= 0:
            return mask.copy()
        
        # 创建圆形结构元素
        y, x = np.ogrid[:2*radius+1, :2*radius+1]
        circle = (x - radius)**2 + (y - radius)**2 <= radius**2
        
        # 将mask转换为二值图（True=障碍，False=可通行）
        obstacles = (mask == 0)
        
        # 对障碍物进行膨胀
        dilated_obstacles = ndimage.binary_dilation(obstacles, structure=circle)
        
        # 转换回mask格式（0=障碍，255=可通行）
        dilated_mask = np.where(dilated_obstacles, 0, 255).astype(np.uint8)
        
        return dilated_mask
    
    def astar_pathfinding(self, start: Tuple[float, float], end: Tuple[float, float], 
                         mask: np.ndarray, scale_factor: float, room_min_x: float, 
                         room_min_y: float, robot_radius_px: int, 
                         use_predilated_mask: bool = False) -> Optional[List[Tuple[int, int]]]:
        """
        A*路径规划算法（优化版：使用预膨胀的mask）
        
        Args:
            start: 起点世界坐标 (x, y)
            end: 终点世界坐标 (x, y)
            mask: 二值mask图 (255=可通行, 0=障碍)
            scale_factor: 缩放因子
            room_min_x, room_min_y: 房间最小坐标
            robot_radius_px: 机器人半径（像素）
            use_predilated_mask: 如果为True，则mask已经预膨胀，不再重复膨胀
            
        Returns:
            路径点列表（像素坐标）或None（如果无法到达）
        """
        # 如果mask已经预膨胀，直接使用；否则进行膨胀操作
        if use_predilated_mask:
            dilated_mask = mask
        else:
            dilated_mask = self._dilate_mask_circular(mask, robot_radius_px)
        
        def world_to_pixel(wx, wy):
            px = int((wx - room_min_x) * scale_factor)
            py = int((wy - room_min_y) * scale_factor)
            py = dilated_mask.shape[0] - 1 - py  # 翻转Y轴
            return px, py
        
        def pixel_to_world(px, py):
            wx = px / scale_factor + room_min_x
            wy = (dilated_mask.shape[0] - 1 - py) / scale_factor + room_min_y
            return wx, wy
        
        def heuristic(p1, p2):
            return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
        
        def is_valid(pixel_x, pixel_y):
            # 优化后：只需要检查单个像素点
            if pixel_x < 0 or pixel_x >= dilated_mask.shape[1] or pixel_y < 0 or pixel_y >= dilated_mask.shape[0]:
                return False
            return dilated_mask[pixel_y, pixel_x] > 0
        
        start_px, start_py = world_to_pixel(start[0], start[1])
        end_px, end_py = world_to_pixel(end[0], end[1])
        
        if not is_valid(start_px, start_py) or not is_valid(end_px, end_py):
            return None
        
        # A*算法
        open_set = [(0, start_px, start_py)]
        came_from = {}
        g_score = {(start_px, start_py): 0}
        f_score = {(start_px, start_py): heuristic((start_px, start_py), (end_px, end_py))}
        closed_set = set()
        
        directions = [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]
        
        while open_set:
            current_f, current_x, current_y = heappop(open_set)
            
            if (current_x, current_y) in closed_set:
                continue
            
            closed_set.add((current_x, current_y))
            
            if current_x == end_px and current_y == end_py:
                # 重构路径
                path = []
                while (current_x, current_y) in came_from:
                    path.append((current_x, current_y))
                    current_x, current_y = came_from[(current_x, current_y)]
                path.append((start_px, start_py))
                path.reverse()
                return path
            
            for dx, dy in directions:
                neighbor_x = current_x + dx
                neighbor_y = current_y + dy
                
                if not is_valid(neighbor_x, neighbor_y):
                    continue
                
                if (neighbor_x, neighbor_y) in closed_set:
                    continue
                
                tentative_g = g_score.get((current_x, current_y), float('inf')) + math.sqrt(dx*dx + dy*dy)
                
                if tentative_g < g_score.get((neighbor_x, neighbor_y), float('inf')):
                    came_from[(neighbor_x, neighbor_y)] = (current_x, current_y)
                    g_score[(neighbor_x, neighbor_y)] = tentative_g
                    h = heuristic((neighbor_x, neighbor_y), (end_px, end_py))
                    f = tentative_g + h
                    f_score[(neighbor_x, neighbor_y)] = f
                    heappush(open_set, (f, neighbor_x, neighbor_y))
        
        return None
    
    def is_point_inside_object(self, point: Tuple[float, float], obj_id: str) -> bool:
        """
        检测点是否在物体内部
        
        Args:
            point: 世界坐标点 (x, y)
            obj_id: 物体ID
            
        Returns:
            True如果点在物体内部，否则False
        """
        obj = None
        for o in self.layout_data.get("objects", []):
            if o.get('id') == obj_id:
                obj = o
                break
        
        if not obj:
            return False
        
        size_info = self.get_object_size(obj_id)
        if not size_info:
            return False
        
        short, long_dim, height = size_info
        pos = obj.get('position', {})
        rot = obj.get('rotation', {})
        
        rotation_z = rot.get('z', 0)
        
        corners = self.get_rotated_rectangle(
            pos.get('x', 0), pos.get('y', 0),
            short, long_dim, rotation_z
        )
        
        # 使用射线法判断点是否在多边形内部
        px, py = point
        inside = False
        n = len(corners)
        
        for i in range(n):
            x1, y1 = corners[i]
            x2, y2 = corners[(i + 1) % n]
            
            if ((y1 > py) != (y2 > py)) and (px < (x2 - x1) * (py - y1) / (y2 - y1) + x1):
                inside = not inside
        
        return inside
    
    def find_objects_covering_point(self, point: Tuple[float, float], floor_only: bool = True) -> List[Tuple[str, int]]:
        """
        找出覆盖指定点的所有物体
        
        Args:
            point: 世界坐标点 (x, y)
            floor_only: 是否只检查地面物体（initial_location == 'floor'），默认为True
            
        Returns:
            覆盖该点的物体列表，每个元素为 (obj_id, obj_index) 元组
        """
        covering_objects = []
        
        for obj_index, obj in enumerate(self.layout_data.get("objects", [])):
            obj_id = obj.get('id')
            if obj_id == 'LaboratoryRoom':
                continue
            
            # 如果只检查地面物体，跳过桌面物体
            if floor_only:
                initial_location = obj.get('initial_location', 'floor')
                if initial_location != 'floor':
                    continue  # 桌面物体不会造成遮挡
            
            if self.is_point_inside_object_direct(point, obj):
                covering_objects.append((obj_id, obj_index))
        
        return covering_objects
    
    def is_point_inside_object_direct(self, point: Tuple[float, float], obj: dict) -> bool:
        """
        直接检测点是否在指定物体对象内部
        
        Args:
            point: 世界坐标点 (x, y)
            obj: 物体对象字典
            
        Returns:
            True如果点在物体内部，否则False
        """
        obj_id = obj.get('id')
        size_info = self.get_object_size(obj_id)
        if not size_info:
            return False
        
        short, long_dim, height = size_info
        pos = obj.get('position', {})
        rot = obj.get('rotation', {})
        
        rotation_z = rot.get('z', 0)
        
        corners = self.get_rotated_rectangle(
            pos.get('x', 0), pos.get('y', 0),
            short, long_dim, rotation_z
        )
        
        # 使用射线法判断点是否在多边形内部
        px, py = point
        inside = False
        n = len(corners)
        
        for i in range(n):
            x1, y1 = corners[i]
            x2, y2 = corners[(i + 1) % n]
            
            if ((y1 > py) != (y2 > py)) and (px < (x2 - x1) * (py - y1) / (y2 - y1) + x1):
                inside = not inside
        
        return inside
    
    def calculate_move_to_nearest_wall(self, obj_id: str, robot_point: Tuple[float, float], 
                                       offset_radius: float) -> dict:
        """
        计算物体移动到最近墙边的调整建议
        
        Args:
            obj_id: 物体ID
            robot_point: 机器人点（起点或终点）(x, y)
            offset_radius: 机器人半径
            
        Returns:
            调整建议字典 {'object': obj_id, 'direction': 'x'/'y', 'distance': float, 'reason': str}
        """
        # 找到物体
        obj = None
        for o in self.layout_data.get("objects", []):
            if o.get('id') == obj_id:
                obj = o
                break
        
        if not obj:
            return {}
        
        return self.calculate_move_to_nearest_wall_direct(obj, robot_point, offset_radius)
    
    def _polygons_too_close(self, poly1: List[Tuple[float, float]], 
                           poly2: List[Tuple[float, float]], 
                           min_distance: float) -> bool:
        """
        检查两个多边形是否太接近
        
        Args:
            poly1: 第一个多边形的顶点列表
            poly2: 第二个多边形的顶点列表
            min_distance: 最小安全距离（米）
        
        Returns:
            True表示距离小于最小安全距离，False表示安全
        """
        # 计算poly1的边界框
        xs1 = [p[0] for p in poly1]
        ys1 = [p[1] for p in poly1]
        min_x1, max_x1 = min(xs1), max(xs1)
        min_y1, max_y1 = min(ys1), max(ys1)
        
        # 计算poly2的边界框
        xs2 = [p[0] for p in poly2]
        ys2 = [p[1] for p in poly2]
        min_x2, max_x2 = min(xs2), max(xs2)
        min_y2, max_y2 = min(ys2), max(ys2)
        
        # 计算边界框之间的距离
        if max_x1 < min_x2:
            dx = min_x2 - max_x1
        elif max_x2 < min_x1:
            dx = min_x1 - max_x2
        else:
            dx = 0  # X方向重叠
        
        if max_y1 < min_y2:
            dy = min_y2 - max_y1
        elif max_y2 < min_y1:
            dy = min_y1 - max_y2
        else:
            dy = 0  # Y方向重叠
        
        # 计算总距离
        if dx > 0 and dy > 0:
            distance = math.sqrt(dx*dx + dy*dy)
        elif dx > 0:
            distance = dx
        elif dy > 0:
            distance = dy
        else:
            distance = 0  # 重叠
        
        return distance < min_distance
    
    def _is_move_safe(self, obj: dict, direction: str, distance: float, 
                     safety_margin: float = 0.01) -> bool:
        """
        检查移动是否安全（不会产生碰撞或越界）
        
        Args:
            obj: 要移动的物体
            direction: 移动方向 ('x' or 'y')
            distance: 移动距离（带符号）
            safety_margin: 安全边距（米，默认1厘米，与GeometryMetrics保持一致）
        
        Returns:
            True表示安全，False表示会产生违规
        """
        # 计算移动后的新位置
        new_pos = obj['position'].copy()
        new_pos[direction] += distance
        
        # 获取物体尺寸和旋转
        obj_id = obj.get('id')
        size_info = self.get_object_size(obj_id)
        if not size_info:
            return False
        
        short, long_dim, height = size_info
        rotation_z = obj.get('rotation', {}).get('z', 0)
        
        # 计算移动后的边界框
        new_corners = self.get_rotated_rectangle(
            new_pos['x'], new_pos['y'],
            short, long_dim, rotation_z
        )
        
        # 检查1: 边界违规（是否超出房间）
        room_size = self.layout_data['room_size']
        room_center_x = self.layout_data['objects'][0]['position']['x']
        room_center_y = self.layout_data['objects'][0]['position']['y']
        
        # 使用与GeometryMetrics一致的墙厚（0.20m）
        WALL_THICKNESS = 0.20
        room_min_x = room_center_x - room_size['w'] / 2 + WALL_THICKNESS
        room_max_x = room_center_x + room_size['w'] / 2 - WALL_THICKNESS
        room_min_y = room_center_y - room_size['d'] / 2 + WALL_THICKNESS
        room_max_y = room_center_y + room_size['d'] / 2 - WALL_THICKNESS
        
        # 检查所有顶点是否在房间内
        for corner in new_corners:
            if not (room_min_x <= corner[0] <= room_max_x and 
                    room_min_y <= corner[1] <= room_max_y):
                return False  # 超出边界
        
        # 检查2: 碰撞违规（是否与其他地面物体碰撞）
        for other_obj in self.layout_data.get('objects', []):
            other_id = other_obj.get('id')
            
            # 跳过自己和房间
            if other_id == obj_id or other_id == 'LaboratoryRoom':
                continue
            
            # 只检查地面物体
            if other_obj.get('initial_location', 'floor') != 'floor':
                continue
            
            # 获取其他物体的边界框
            other_size = self.get_object_size(other_id)
            if not other_size:
                continue
            
            other_short, other_long, _ = other_size
            other_rotation_z = other_obj.get('rotation', {}).get('z', 0)
            
            other_corners = self.get_rotated_rectangle(
                other_obj['position']['x'],
                other_obj['position']['y'],
                other_short, other_long,
                other_rotation_z
            )
            
            # 检查两个多边形是否相交或距离过近
            if self._polygons_too_close(new_corners, other_corners, safety_margin):
                return False  # 碰撞
        
        return True  # 安全
    
    def calculate_move_away_from_point(self, blocking_obj: dict, 
                                       covered_point: Tuple[float, float],
                                       robot_radius: float) -> dict:
        """
        计算让遮挡物远离被遮挡点的移动建议（新逻辑）
        
        Args:
            blocking_obj: 遮挡物体
            covered_point: 被遮挡的点（起点或终点的机器人停靠位置）
            robot_radius: 机器人半径
        
        Returns:
            调整建议字典 {'object': obj_id, 'direction': 'x'/'y', 'distance': float, 'reason': str}
        """
        # Step 1: 获取遮挡物的基本信息
        obj_id = blocking_obj.get('id')
        obj_pos = blocking_obj.get('position', {})
        obj_center = (obj_pos.get('x', 0), obj_pos.get('y', 0))
        
        # 获取物体尺寸
        size_info = self.get_object_size(obj_id)
        if not size_info:
            return {}
        
        short, long_dim, height = size_info
        obj_radius = max(short, long_dim) / 2  # 近似半径
        
        # Step 2: 计算远离向量
        dx = obj_center[0] - covered_point[0]
        dy = obj_center[1] - covered_point[1]
        
        # 距离
        current_distance = math.sqrt(dx*dx + dy*dy)
        
        if current_distance < 0.01:
            # 几乎重合，默认向右移动
            if self._is_move_safe(blocking_obj, 'x', 0.5):
                return {
                    'object': obj_id,
                    'direction': 'x',
                    'distance': 0.5,
                    'reason': '位置重合，默认分离'
                }
            elif self._is_move_safe(blocking_obj, 'y', 0.5):
                return {
                    'object': obj_id,
                    'direction': 'y',
                    'distance': 0.5,
                    'reason': '位置重合，默认分离'
                }
            return {}
        
        # Step 3: 确定主方向和次方向
        if abs(dx) >= abs(dy):
            primary_dir = 'x'
            primary_sign = 1 if dx > 0 else -1
            secondary_dir = 'y'
            secondary_sign = 1 if dy > 0 else -1
        else:
            primary_dir = 'y'
            primary_sign = 1 if dy > 0 else -1
            secondary_dir = 'x'
            secondary_sign = 1 if dx > 0 else -1
        
        # Step 4: 计算最小分离距离
        min_clearance = obj_radius + robot_radius + 0.15
        overlap = max(0, min_clearance - current_distance)
        min_move_distance = overlap + 0.1
        
        # Step 5: 尝试主方向移动
        if self._is_move_safe(blocking_obj, primary_dir, primary_sign * min_move_distance):
            return {
                'object': obj_id,
                'direction': primary_dir,
                'distance': primary_sign * min_move_distance,
                'reason': f'远离目标点（主方向{primary_dir}）'
            }
        
        # Step 6: 主方向不安全，尝试次方向
        if self._is_move_safe(blocking_obj, secondary_dir, secondary_sign * min_move_distance):
            return {
                'object': obj_id,
                'direction': secondary_dir,
                'distance': secondary_sign * min_move_distance,
                'reason': f'远离目标点（次方向{secondary_dir}）'
            }
        
        # Step 7: 尝试增大移动距离
        larger_distance = min_move_distance * 1.5
        if self._is_move_safe(blocking_obj, primary_dir, primary_sign * larger_distance):
            return {
                'object': obj_id,
                'direction': primary_dir,
                'distance': primary_sign * larger_distance,
                'reason': f'远离目标点（增大距离）'
            }
        
        # Step 8: 尝试反方向
        if self._is_move_safe(blocking_obj, primary_dir, -primary_sign * min_move_distance):
            return {
                'object': obj_id,
                'direction': primary_dir,
                'distance': -primary_sign * min_move_distance,
                'reason': f'反向移动（主方向受阻）'
            }
        
        # Step 9: 所有严格安全的方向都失败，使用宽容模式
        # 选择主方向，即使可能产生轻微违规，让布局优化器来修复
        print(f"警告: {obj_id} 所有方向都受阻，使用宽容模式（主方向）")
        return {
            'object': obj_id,
            'direction': primary_dir,
            'distance': primary_sign * min_move_distance,
            'reason': f'远离目标点（宽容模式，可能需要布局优化器修复）'
        }
    
    def calculate_move_to_nearest_wall_direct(self, obj: dict, robot_point: Tuple[float, float], 
                                              offset_radius: float) -> dict:
        """
        计算物体移动到最近墙边的调整建议（直接接受物体对象）
        【已废弃，保留用于兼容】
        
        Args:
            obj: 物体对象字典
            robot_point: 机器人点（起点或终点）(x, y)
            offset_radius: 机器人半径
            
        Returns:
            调整建议字典 {'object': obj_id, 'direction': 'x'/'y', 'distance': float, 'reason': str}
        """
        obj_id = obj.get('id')
        
        # 获取物体中心点
        pos = obj.get('position', {})
        obj_center_x = pos.get('x', 0)
        obj_center_y = pos.get('y', 0)
        
        # 获取房间边界
        room_size = self.layout_data['room_size']
        room_width = room_size['w']
        room_depth = room_size['d']
        room_center_x = self.layout_data['objects'][0]['position']['x']
        room_center_y = self.layout_data['objects'][0]['position']['y']
        
        room_min_x = room_center_x - room_width / 2
        room_max_x = room_center_x + room_width / 2
        room_min_y = room_center_y - room_depth / 2
        room_max_y = room_center_y + room_depth / 2
        
        # 计算物体中心到4个墙的距离
        dist_to_left = obj_center_x - room_min_x
        dist_to_right = room_max_x - obj_center_x
        dist_to_bottom = obj_center_y - room_min_y
        dist_to_top = room_max_y - obj_center_y
        
        # 找最近的墙
        distances = {
            'left': dist_to_left,
            'right': dist_to_right,
            'bottom': dist_to_bottom,
            'top': dist_to_top
        }
        nearest_wall = min(distances, key=distances.get)
        
        # 根据最近的墙确定移动方向和距离
        robot_x, robot_y = robot_point
        
        if nearest_wall in ['left', 'right']:
            # 移动方向是x
            direction = 'x'
            base_distance = abs(robot_x - obj_center_x) + offset_radius + 0.1
            # 确定移动符号：朝最近的墙移动
            if nearest_wall == 'left':
                distance = -base_distance  # 向左移动
            else:
                distance = base_distance  # 向右移动
        else:
            # 移动方向是y
            direction = 'y'
            base_distance = abs(robot_y - obj_center_y) + offset_radius + 0.1
            # 确定移动符号：朝最近的墙移动
            if nearest_wall == 'bottom':
                distance = -base_distance  # 向下移动
            else:
                distance = base_distance  # 向上移动
        
        return {
            'object': obj_id,
            'direction': direction,
            'distance': distance,
            'reason': f'覆盖机器人目标点，移向{nearest_wall}墙'
        }
    
    def point_to_line_distance(self, point: Tuple[float, float], 
                               line_start: Tuple[float, float], 
                               line_end: Tuple[float, float]) -> float:
        """计算点到线段的距离"""
        px, py = point
        x1, y1 = line_start
        x2, y2 = line_end
        
        # 线段长度的平方
        line_len_sq = (x2 - x1)**2 + (y2 - y1)**2
        if line_len_sq < 1e-10:
            # 起点和终点重合，返回点到点的距离
            return math.sqrt((px - x1)**2 + (py - y1)**2)
        
        # 计算投影参数t
        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))
        
        # 线段上最近的点
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)
        
        # 返回点到投影点的距离
        return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
    
    def bbox_to_line_distance(self, bbox: Tuple[float, float, float, float],
                              line_start: Tuple[float, float],
                              line_end: Tuple[float, float]) -> float:
        """计算边界框到线段的最小距离"""
        min_x, max_x, min_y, max_y = bbox
        
        # 检查线段是否与边界框相交
        # 简化：检查线段的端点是否在边界框内
        x1, y1 = line_start
        x2, y2 = line_end
        
        # 如果线段端点都在边界框内，距离为0
        if (min_x <= x1 <= max_x and min_y <= y1 <= max_y) or \
           (min_x <= x2 <= max_x and min_y <= y2 <= max_y):
            return 0
        
        # 计算边界框的四个角点到线段的距离
        corners = [
            (min_x, min_y), (max_x, min_y),
            (max_x, max_y), (min_x, max_y)
        ]
        
        min_dist = float('inf')
        for corner in corners:
            dist = self.point_to_line_distance(corner, line_start, line_end)
            min_dist = min(min_dist, dist)
        
        # 如果线段与边界框相交，距离为0
        # 简化检查：如果线段穿过边界框，距离为0
        if not (max(x1, x2) < min_x or min(x1, x2) > max_x or 
                max(y1, y2) < min_y or min(y1, y2) > max_y):
            # 线段可能与边界框相交
            min_dist = min(min_dist, 0)
        
        return min_dist
    
    def find_blocking_objects(self, start_pos: Tuple[float, float], end_pos: Tuple[float, float],
                             min_gap: float) -> List[Tuple[str, str]]:
        """
        查找阻塞路径的物体对（只返回真正阻塞起点到终点路径的物体对）
        
        Args:
            start_pos: 起点世界坐标 (x, y)
            end_pos: 终点世界坐标 (x, y)
            min_gap: 最小可通过间距（米）
            
        Returns:
            阻塞物体对列表 [(obj1_id, obj2_id), ...]，只包含真正阻塞路径的物体对
        """
        blocking_pairs = []
        
        # 获取所有物体及其边界框（只考虑地面物体）
        objects_info = []
        for obj in self.layout_data.get("objects", []):
            obj_id = obj.get('id')
            if obj_id == 'LaboratoryRoom':
                continue
            
            # 只考虑地面物体，桌面物体不会阻塞路径
            initial_location = obj.get('initial_location', 'floor')
            if initial_location != 'floor':
                continue
            
            size_info = self.get_object_size(obj_id)
            if size_info is None:
                continue
            
            short, long_dim, height = size_info
            pos = obj.get('position', {})
            rot = obj.get('rotation', {})
            
            rotation_z = rot.get('z', 0)
            
            corners = self.get_rotated_rectangle(
                pos.get('x', 0), pos.get('y', 0),
                short, long_dim, rotation_z
            )
            
            # 计算物体的边界框（轴对齐）
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            
            objects_info.append({
                'id': obj_id,
                'corners': corners,
                'center': (pos.get('x', 0), pos.get('y', 0)),
                'bbox': (min_x, max_x, min_y, max_y)
            })
        
        # 找出路径附近的物体
        path_nearby_objects = []
        for obj_info in objects_info:
            bbox_dist = self.bbox_to_line_distance(obj_info['bbox'], start_pos, end_pos)
            # 如果物体距离路径较近（考虑物体大小和最小间距）
            if bbox_dist < min_gap + 2.0:  # 2.0米缓冲，放宽条件
                path_nearby_objects.append(obj_info)
        
        # 如果路径附近没有物体，检查所有距离较近的物体对
        if not path_nearby_objects:
            # 检查所有物体对，找出距离较近的
            for i, obj1 in enumerate(objects_info):
                for j, obj2 in enumerate(objects_info[i+1:], i+1):
                    min_x1, max_x1, min_y1, max_y1 = obj1['bbox']
                    min_x2, max_x2, min_y2, max_y2 = obj2['bbox']
                    
                    if max_x1 < min_x2:
                        dx = min_x2 - max_x1
                    elif max_x2 < min_x1:
                        dx = min_x1 - max_x2
                    else:
                        dx = 0
                    
                    if max_y1 < min_y2:
                        dy = min_y2 - max_y1
                    elif max_y2 < min_y1:
                        dy = min_y1 - max_y2
                    else:
                        dy = 0
                    
                    if dx > 0 and dy > 0:
                        dist = math.sqrt(dx*dx + dy*dy)
                    elif dx > 0:
                        dist = dx
                    elif dy > 0:
                        dist = dy
                    else:
                        dist = 0
                    
                    # 如果距离小于最小间距，认为是潜在的阻塞对
                    if dist < min_gap:
                        blocking_pairs.append((obj1['id'], obj2['id']))
        else:
            # 只检查路径附近的物体对
            for i, obj1 in enumerate(path_nearby_objects):
                for j, obj2 in enumerate(path_nearby_objects[i+1:], i+1):
                    # 计算两个物体边界框之间的最小距离
                    min_x1, max_x1, min_y1, max_y1 = obj1['bbox']
                    min_x2, max_x2, min_y2, max_y2 = obj2['bbox']
                    
                    # 计算两个矩形之间的最小距离
                    if max_x1 < min_x2:
                        dx = min_x2 - max_x1
                    elif max_x2 < min_x1:
                        dx = min_x1 - max_x2
                    else:
                        dx = 0
                    
                    if max_y1 < min_y2:
                        dy = min_y2 - max_y1
                    elif max_y2 < min_y1:
                        dy = min_y1 - max_y2
                    else:
                        dy = 0
                    
                    if dx > 0 and dy > 0:
                        dist = math.sqrt(dx*dx + dy*dy)
                    elif dx > 0:
                        dist = dx
                    elif dy > 0:
                        dist = dy
                    else:
                        dist = 0  # 重叠
                    
                    # 检查这两个物体之间的间隙是否在路径上
                    # 计算两个物体中心的中点
                    mid_x = (obj1['center'][0] + obj2['center'][0]) / 2
                    mid_y = (obj1['center'][1] + obj2['center'][1]) / 2
                    mid_point = (mid_x, mid_y)
                    
                    # 检查中点是否在路径附近
                    mid_to_path_dist = self.point_to_line_distance(mid_point, start_pos, end_pos)
                    
                    # 如果距离小于最小间距要求，且中点距离路径较近，则认为是阻塞对
                    # 放宽条件：距离路径3米范围内都考虑
                    if dist < min_gap and mid_to_path_dist < 3.0:
                        blocking_pairs.append((obj1['id'], obj2['id']))
        
        return blocking_pairs
    
    def calculate_adjustment(self, obj1_id: str, obj2_id: str, min_gap: float) -> dict:
        """
        计算物体调整方向和距离
        
        Args:
            obj1_id, obj2_id: 两个物体的ID
            min_gap: 最小间距要求（米）
            
        Returns:
            调整建议字典
        """
        obj1 = None
        obj2 = None
        
        for obj in self.layout_data.get("objects", []):
            if obj.get('id') == obj1_id:
                obj1 = obj
            if obj.get('id') == obj2_id:
                obj2 = obj
        
        if not obj1 or not obj2:
            return {}
        
        # 获取物体尺寸
        size1 = self.get_object_size(obj1_id)
        size2 = self.get_object_size(obj2_id)
        
        if not size1 or not size2:
            return {}
        
        short1, long1, _ = size1
        short2, long2, _ = size2
        
        pos1 = obj1.get('position', {})
        pos2 = obj2.get('position', {})
        
        cx1, cy1 = pos1.get('x', 0), pos1.get('y', 0)
        cx2, cy2 = pos2.get('x', 0), pos2.get('y', 0)
        
        dx = cx2 - cx1
        dy = cy2 - cy1
        
        # 计算当前距离
        current_dist = math.sqrt(dx*dx + dy*dy)
        if current_dist < 0.01:
            # 如果重叠，默认向X方向分离
            required_separation = (short1 + short2) / 2 + min_gap
            return {
                'object1': obj1_id,
                'object2': obj2_id,
                'adjustments': [
                    {'object': obj1_id, 'direction': 'x', 'distance': -required_separation / 2},
                    {'object': obj2_id, 'direction': 'x', 'distance': required_separation / 2}
                ]
            }
        
        # 计算需要的总分离距离
        # 考虑物体尺寸和最小间距
        required_dist = (short1 + short2) / 2 + min_gap
        needed_separation = required_dist - current_dist
        
        if needed_separation <= 0:
            return {}  # 已经满足间距要求
        
        # 计算单位方向向量
        unit_x = dx / current_dist
        unit_y = dy / current_dist
        
        # 计算每个物体需要移动的距离（各移动一半）
        move_dist = needed_separation / 2
        
        # 判断主要移动方向
        if abs(dx) > abs(dy):
            direction = 'x'
            move_x1 = -unit_x * move_dist
            move_x2 = unit_x * move_dist
            return {
                'object1': obj1_id,
                'object2': obj2_id,
                'adjustments': [
                    {'object': obj1_id, 'direction': 'x', 'distance': move_x1},
                    {'object': obj2_id, 'direction': 'x', 'distance': move_x2}
                ]
            }
        else:
            direction = 'y'
            move_y1 = -unit_y * move_dist
            move_y2 = unit_y * move_dist
            return {
                'object1': obj1_id,
                'object2': obj2_id,
                'adjustments': [
                    {'object': obj1_id, 'direction': 'y', 'distance': move_y1},
                    {'object': obj2_id, 'direction': 'y', 'distance': move_y2}
                ]
            }
    
    def analyze_navigation_paths(self, protocol_json_path: str, 
                                 robot_radius: float = 0.6, 
                                 min_gap: float = 1.2,
                                 scale_factor: float = 200) -> dict:
        """
        分析导航路径，检测阻塞并生成调整建议
        
        Args:
            protocol_json_path: protocol JSON文件路径
            robot_radius: 机器人半径（米）
            min_gap: 最小可通过间距（米）
            scale_factor: mask图缩放因子
            
        Returns:
            分析结果JSON字典
        """
        if self.layout_data is None:
            self.load_data()
        
        # 生成mask图（内存中）
        room_size = self.layout_data['room_size']
        room_width = room_size['w']
        room_depth = room_size['d']
        
        img_width_px = int(room_width * scale_factor)
        img_height_px = int(room_depth * scale_factor)
        
        room_center_x = self.layout_data['objects'][0]['position']['x']
        room_center_y = self.layout_data['objects'][0]['position']['y']
        room_min_x = room_center_x - room_width / 2
        room_min_y = room_center_y - room_depth / 2
        
        mask = np.ones((img_height_px, img_width_px), dtype=np.uint8) * 255
        
        def world_to_pixel(wx, wy):
            px = int((wx - room_min_x) * scale_factor)
            py = int((wy - room_min_y) * scale_factor)
            py = img_height_px - 1 - py
            return px, py
        
        for obj in self.layout_data['objects']:
            obj_id = obj['id']
            if obj_id == 'LaboratoryRoom':
                continue
            
            # 只将地面物体绘制为障碍物
            initial_location = obj.get('initial_location', 'floor')
            if initial_location != 'floor':
                continue
            
            size_info = self.get_object_size(obj_id)
            if size_info is None:
                px, py = world_to_pixel(obj['position']['x'], obj['position']['y'])
                if 0 <= px < img_width_px and 0 <= py < img_height_px:
                    mask[py, px] = 0
                continue
            
            short, long_dim, height = size_info
            rotation_z = obj.get('rotation', {}).get('z', 0)
            
            corners = self.get_rotated_rectangle(
                obj['position']['x'], obj['position']['y'],
                short, long_dim, rotation_z
            )
            
            pixel_corners = [world_to_pixel(cx, cy) for cx, cy in corners]
            img = Image.fromarray(mask)
            draw = ImageDraw.Draw(img)
            draw.polygon(pixel_corners, fill=0)
            mask = np.array(img)
        
        # 获取导航点序列
        nav_points = self.get_nav_points_from_protocol(protocol_json_path, robot_radius)
        
        robot_radius_px = int(robot_radius * scale_factor)
        
        # 预先膨胀mask一次（避免在循环中重复膨胀）
        print("正在预处理mask（膨胀操作）...")
        dilated_mask = self._dilate_mask_circular(mask, robot_radius_px)
        print("Mask预处理完成")
        
        results = {}
        
        total_paths = len(nav_points) - 1
        print(f"开始分析 {total_paths} 条导航路径...")
        
        # 分析每对相邻的导航点
        for i in range(len(nav_points) - 1):
            print(f"  分析路径 {i+1}/{total_paths}...", end=' ')
            start_point = nav_points[i]
            end_point = nav_points[i + 1]
            
            start_obj = start_point['object_id']
            end_obj = end_point['object_id']
            path_key = f"{start_obj}->{end_obj}"
            
            start_pos = (start_point['x'], start_point['y'])
            end_pos = (end_point['x'], end_point['y'])
            
            # 检查起点和终点是否非常接近（距离小于1厘米）
            distance = math.sqrt((end_pos[0] - start_pos[0])**2 + (end_pos[1] - start_pos[1])**2)
            if distance < 0.01:
                # 起点终点几乎重合，直接标记为可达
                print("起点终点重合，跳过")
                result_entry = {
                    "reachable": True,
                    "start": {
                        "x": start_point['x'],
                        "y": start_point['y'],
                        "object_id": start_obj,
                        "step_number": start_point.get('step_number'),
                        "location": start_point.get('location')
                    },
                    "end": {
                        "x": end_point['x'],
                        "y": end_point['y'],
                        "object_id": end_obj,
                        "step_number": end_point.get('step_number'),
                        "location": end_point.get('location')
                    },
                    "adjustments": [],
                    "path": None  # 距离太近，无需路径
                }
                results[path_key] = result_entry
                continue
            
            # A*路径规划（使用预膨胀的mask）
            path = self.astar_pathfinding(
                start_pos, end_pos, dilated_mask, scale_factor,
                room_min_x, room_min_y, robot_radius_px,
                use_predilated_mask=True
            )
            
            # 保存起点和终点信息
            result_entry = {
                "reachable": False,
                "start": {
                    "x": start_point['x'],
                    "y": start_point['y'],
                    "object_id": start_obj,
                    "step_number": start_point.get('step_number'),
                    "location": start_point.get('location')
                },
                "end": {
                    "x": end_point['x'],
                    "y": end_point['y'],
                    "object_id": end_obj,
                    "step_number": end_point.get('step_number'),
                    "location": end_point.get('location')
                },
                "adjustments": [],
                "path": None  # 用于保存实际路径
            }
            
            if path is not None:
                result_entry["reachable"] = True
                result_entry["path"] = path  # 保存路径数据
                print("可达")
            else:
                print("不可达")
                
                # 首先检查起点和终点是否被物体覆盖
                start_covering = self.find_objects_covering_point(start_pos)
                end_covering = self.find_objects_covering_point(end_pos)
                
                # 过滤掉起点/终点所属的物体（机器人本来就要去那里）
                start_covering = [(obj_id, idx) for obj_id, idx in start_covering if obj_id != start_obj]
                end_covering = [(obj_id, idx) for obj_id, idx in end_covering if obj_id != end_obj]
                
                if start_covering or end_covering:
                    # 起点或终点被物体覆盖，直接要求移动该物体到最近的墙

                    adjustments = []
                    
                    if start_covering:
                        print(f"覆盖起点 {start_obj}: {[f'{obj_id}[{idx}]' for obj_id, idx in start_covering]}")
                        for obj_id, obj_index in start_covering:
                            obj = self.layout_data['objects'][obj_index]
                            # 使用新逻辑：让遮挡物远离起点
                            adj = self.calculate_move_away_from_point(
                                obj, start_pos, robot_radius
                            )
                            if adj:
                                adj['reason'] = f'覆盖起点 {start_obj}'
                                adj['object_index'] = obj_index
                                adjustments.append(adj)
                    
                    if end_covering:
                        print(f"覆盖终点 {end_obj}: {[f'{obj_id}[{idx}]' for obj_id, idx in end_covering]}")
                        for obj_id, obj_index in end_covering:
                            obj = self.layout_data['objects'][obj_index]
                            # 使用新逻辑：让遮挡物远离终点
                            adj = self.calculate_move_away_from_point(
                                obj, end_pos, robot_radius
                            )
                            if adj:
                                adj['reason'] = f'覆盖终点 {end_obj}'
                                adj['object_index'] = obj_index
                                adjustments.append(adj)
                    
                    result_entry["adjustments"] = adjustments
                else:
                    # 路径不可达，查找阻塞物体
                    blocking_pairs = self.find_blocking_objects(
                        start_pos, end_pos, min_gap
                    )
                    
                    # 如果找到多个阻塞对，只选择最关键的（距离路径最近的）
                    if blocking_pairs:
                        # 计算每个阻塞对到路径的距离，选择最近的
                        best_pair = None
                        min_path_dist = float('inf')
                        
                        for obj1_id, obj2_id in blocking_pairs:
                            # 获取两个物体的中心点
                            obj1 = None
                            obj2 = None
                            for obj in self.layout_data.get("objects", []):
                                if obj.get('id') == obj1_id:
                                    obj1 = obj
                                if obj.get('id') == obj2_id:
                                    obj2 = obj
                            
                            if obj1 and obj2:
                                pos1 = obj1.get('position', {})
                                pos2 = obj2.get('position', {})
                                mid_x = (pos1.get('x', 0) + pos2.get('x', 0)) / 2
                                mid_y = (pos1.get('y', 0) + pos2.get('y', 0)) / 2
                                mid_point = (mid_x, mid_y)
                                
                                # 计算中点到路径的距离
                                dist_to_path = self.point_to_line_distance(mid_point, start_pos, end_pos)
                                
                                if dist_to_path < min_path_dist:
                                    min_path_dist = dist_to_path
                                    best_pair = (obj1_id, obj2_id)
                        
                        # 只对最关键的阻塞对生成调整建议
                        if best_pair:
                            obj1_id, obj2_id = best_pair
                            adj = self.calculate_adjustment(obj1_id, obj2_id, min_gap)
                            if adj and 'adjustments' in adj:
                                result_entry["adjustments"] = adj['adjustments']
            
            results[path_key] = result_entry
        
        # 添加旋转修复建议（针对面向墙面的设备）
        if hasattr(self, '_rotation_fixes') and self._rotation_fixes:
            print(f"\n发现 {len(self._rotation_fixes)} 个面向墙面的设备，建议旋转180°")
            rotation_adjustments = []
            for fix in self._rotation_fixes:
                rotation_adjustments.append({
                    'object_id': fix['object_id'],
                    'adjustment_type': 'rotation_fix',
                    'current_rotation': fix['current_rotation'],
                    'suggested_rotation': fix['suggested_rotation'],
                    'reason': '设备面向墙面，操作点在房间外',
                    'step_number': fix.get('step_number'),
                    'location': fix.get('location')
                })
            
            # 将旋转修复添加到results的元数据中
            results['_rotation_fixes'] = rotation_adjustments
        
        print("路径分析完成")
        return results
    
    def visualize_navigation_paths(self, results: dict, output_path: str, 
                                   dpi: int = 300, scale_factor: float = 200):
        """
        可视化导航路径分析结果，标注起点和终点
        
        Args:
            results: analyze_navigation_paths返回的结果字典
            output_path: 输出PNG文件路径
            dpi: 图片分辨率
            scale_factor: 缩放因子
        """
        print("正在生成可视化图...")
        if self.layout_data is None:
            self.load_data()
        
        room_size = self.layout_data['room_size']
        room_width = room_size['w']
        room_depth = room_size['d']
        
        room_center_x = self.layout_data['objects'][0]['position']['x']
        room_center_y = self.layout_data['objects'][0]['position']['y']
        room_min_x = room_center_x - room_width / 2
        room_min_y = room_center_y - room_depth / 2
        room_max_x = room_center_x + room_width / 2
        room_max_y = room_center_y + room_depth / 2
        
        img_height_px = int(room_depth * scale_factor)
        
        # 像素到世界坐标的转换函数
        def pixel_to_world(px, py):
            wx = px / scale_factor + room_min_x
            wy = (img_height_px - 1 - py) / scale_factor + room_min_y
            return wx, wy
        
        # 创建图形
        fig, ax = plt.subplots(figsize=(room_width*2, room_depth*2), dpi=dpi)
        ax.set_xlim(room_min_x, room_max_x)
        ax.set_ylim(room_min_y, room_max_y)
        ax.set_aspect('equal')
        ax.set_xlabel('X (m)')
        ax.set_ylabel('Y (m)')
        ax.set_title('Navigation Paths Analysis')
        
        # 绘制房间边界
        room_rect = Rectangle((room_min_x, room_min_y), room_width, room_depth, 
                             linewidth=2, edgecolor='black', facecolor='lightgray', alpha=0.3)
        ax.add_patch(room_rect)
        
        # 绘制所有物体
        for obj in self.layout_data['objects']:
            obj_id = obj['id']
            if obj_id == 'LaboratoryRoom':
                continue
            
            size_info = self.get_object_size(obj_id)
            if size_info is None:
                ax.plot(obj['position']['x'], obj['position']['y'], 'ro', markersize=5)
                continue
            
            short, long_dim, height = size_info
            rotation_z = obj.get('rotation', {}).get('z', 0)
            
            corners = self.get_rotated_rectangle(
                obj['position']['x'], obj['position']['y'],
                short, long_dim, rotation_z
            )
            
            polygon = Polygon(corners, closed=True, 
                            edgecolor='blue', facecolor='lightblue', 
                            alpha=0.6, linewidth=1)
            ax.add_patch(polygon)
            
            ax.text(obj['position']['x'], obj['position']['y'], obj_id, 
                   fontsize=6, ha='center', va='center',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))
        
        # 绘制导航路径和起点终点
        colors = plt.cm.tab10(np.linspace(0, 1, len(results)))
        for idx, (path_key, result) in enumerate(results.items()):
            start = result['start']
            end = result['end']
            reachable = result['reachable']
            
            start_pos = (start['x'], start['y'])
            end_pos = (end['x'], end['y'])
            color = colors[idx]
            
            # 绘制起点（绿色）
            ax.plot(start_pos[0], start_pos[1], 'o', color='green', 
                   markersize=10, label='Start' if idx == 0 else '')
            ax.text(start_pos[0], start_pos[1] + 0.3, 
                   f"S{start.get('step_number', '?')}\n{start['object_id']}", 
                   fontsize=7, ha='center', va='bottom',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgreen', alpha=0.8))
            
            # 绘制终点（红色）
            ax.plot(end_pos[0], end_pos[1], 's', color='red', 
                   markersize=10, label='End' if idx == 0 else '')
            ax.text(end_pos[0], end_pos[1] + 0.3, 
                   f"E{end.get('step_number', '?')}\n{end['object_id']}", 
                   fontsize=7, ha='center', va='bottom',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='lightcoral', alpha=0.8))
            
            # 绘制路径线
            if reachable and result.get('path'):
                # 绘制真实路径
                path_pixels = result['path']
                path_world = [pixel_to_world(px, py) for px, py in path_pixels]
                
                if path_world:
                    path_x = [p[0] for p in path_world]
                    path_y = [p[1] for p in path_world]
                    ax.plot(path_x, path_y, '-', color=color, linewidth=2, alpha=0.7, label=path_key)
            elif reachable:
                # 没有路径数据，绘制直线
                ax.plot([start_pos[0], end_pos[0]], [start_pos[1], end_pos[1]], 
                       '--', color=color, linewidth=2, alpha=0.7, label=path_key)
            else:
                # 不可达，绘制虚线
                ax.plot([start_pos[0], end_pos[0]], [start_pos[1], end_pos[1]], 
                       ':', color=color, linewidth=2, alpha=0.5, label=f"{path_key} (不可达)")
        
        ax.legend(loc='upper right', fontsize=8)
        plt.tight_layout()
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight', format='png')
        plt.close()
        
        print(f"导航路径可视化图已保存到: {output_path}")


def process_single_subdir(args_tuple):
    """
    处理单个子目录的导航分析（用于并行处理）
    
    Args:
        args_tuple: (subdir, assets_json, output_base_dir) 元组
    
    Returns:
        (subdir_name, success, message) 元组
    """
    subdir, assets_json, output_base_dir = args_tuple
    subdir_name = subdir.name
    
    try:
        # 查找必需的文件（支持两种格式）
        layout_files = list(subdir.glob("*_room_isaacsim.json"))
        if not layout_files:
            # 尝试查找优化后的布局文件
            layout_files = list(subdir.glob("*_optimized.json"))
        
        protocol_files = list(subdir.glob("protocol_*.json"))
        
        # 检查是否找到必需文件
        if not layout_files:
            return (subdir_name, False, "未找到布局文件 (*_room_isaacsim.json 或 *_optimized.json)")
        
        if not protocol_files:
            return (subdir_name, False, "未找到协议文件 (protocol_*.json)")
        
        layout_json = str(layout_files[0])
        protocol_json = str(protocol_files[0])
        
        # 创建输出目录
        output_dir = Path(output_base_dir) / subdir_name
        os.makedirs(output_dir, exist_ok=True)
        
        # 创建优化器实例
        optimizer = NavigationIterativeOptimizer(layout_json, assets_json)
        
        # 生成俯视图
        try:
            output_png = output_dir / "layout_top_view.png"
            optimizer.generate_top_view(str(output_png), dpi=300, scale_factor=200)
        except Exception as e:
            return (subdir_name, False, f"生成俯视图失败: {str(e)}")
        
        # 生成mask图
        try:
            mask_png = output_dir / "layout_mask.png"
            optimizer.generate_mask(str(mask_png), scale_factor=200)
        except Exception as e:
            return (subdir_name, False, f"生成mask图失败: {str(e)}")
        
        # 分析导航路径
        try:
            results = optimizer.analyze_navigation_paths(
                protocol_json_path=protocol_json,
                robot_radius=0.3,
                min_gap=1.2,
                scale_factor=200
            )
        except Exception as e:
            return (subdir_name, False, f"分析导航路径失败: {str(e)}")
        
        # 保存结果到JSON文件
        output_json = output_dir / "navigation_analysis_results.json"
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        # 生成可视化图
        try:
            viz_output = output_dir / "navigation_paths_visualization.png"
            optimizer.visualize_navigation_paths(results, str(viz_output), dpi=300, scale_factor=200)
        except Exception as e:
            # 可视化失败不算致命错误
            pass
        
        # 统计结果
        reachable_count = sum(1 for r in results.values() if r['reachable'])
        unreachable_count = len(results) - reachable_count
        
        message = f"完成 | 路径: {len(results)} | 可达: {reachable_count} | 不可达: {unreachable_count}"
        return (subdir_name, True, message)
        
    except Exception as e:
        import traceback
        error_msg = f"处理失败: {str(e)}\n{traceback.format_exc()}"
        return (subdir_name, False, error_msg)


if __name__ == "__main__":
    import os
    import argparse
    from glob import glob
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from multiprocessing import cpu_count
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='实验室布局导航路径分析器（并行版本）')
    parser.add_argument('--data-dir', type=str, default='data',
                        help='输入数据目录路径（包含子目录，每个子目录有布局和协议文件）')
    parser.add_argument('--output-dir', type=str, default='output',
                        help='输出结果目录路径')
    parser.add_argument('--assets', type=str, 
                        default='data/assets_annotated.json',
                        help='资产尺寸JSON文件路径')
    parser.add_argument('--workers', type=int, default=30,
                        help=f'并行worker数量（默认: 30，系统CPU核心数={cpu_count()}）')
    args = parser.parse_args()
    
    # 全局资产文件
    assets_json = args.assets
    data_dir = args.data_dir
    output_base_dir = args.output_dir
    workers = args.workers  # 默认30
    
    # 创建输出根目录
    os.makedirs(output_base_dir, exist_ok=True)
    
    # 遍历data文件夹下的所有子文件夹
    subdirs = [d for d in Path(data_dir).iterdir() if d.is_dir()]
    
    total_subdirs = len(subdirs)
    print(f"找到 {total_subdirs} 个子文件夹")
    print(f"使用 {workers} 个并行worker")
    print("=" * 80)
    
    # 准备任务参数
    tasks = [(subdir, assets_json, output_base_dir) for subdir in subdirs]
    
    # 并行处理
    success_count = 0
    fail_count = 0
    
    with ProcessPoolExecutor(max_workers=workers) as executor:
        # 提交所有任务
        future_to_subdir = {executor.submit(process_single_subdir, task): task[0] for task in tasks}
        
        # 处理完成的任务
        for idx, future in enumerate(as_completed(future_to_subdir), 1):
            subdir = future_to_subdir[future]
            try:
                subdir_name, success, message = future.result()
                
                status = "✓" if success else "✗"
                print(f"[{idx}/{total_subdirs}] {status} {subdir_name}")
                print(f"    {message}")
                
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    
            except Exception as e:
                print(f"[{idx}/{total_subdirs}] ✗ {subdir.name}")
                print(f"    异常: {str(e)}")
                fail_count += 1
    
    print("\n" + "=" * 80)
    print("批量处理完成")
    print(f"总计: {total_subdirs} | 成功: {success_count} | 失败: {fail_count}")
