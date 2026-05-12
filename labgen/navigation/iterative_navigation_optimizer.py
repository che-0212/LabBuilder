#!/usr/bin/env python3
"""
导航迭代优化器 - 结合导航分析和布局优化的迭代优化

主要功能：
1. 读取导航分析结果的 adjustments
2. 应用调整到布局（包括同步移动平台上的物品）
3. 调用布局优化脚本
4. 再次进行导航分析
5. 迭代直到收敛或达到最大迭代次数

使用方法:
    python iterative_navigation_optimizer.py --data-dir <输入目录> --max-iterations 5
"""

import json
import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import math


class IterativeNavigationOptimizer:
    """导航迭代优化器"""
    
    def __init__(self, data_dir: str, max_iterations: int = 5, 
                 robot_radius: float = 0.3, min_gap: float = 1.2,
                 layout_workers: int = 150, layout_max_iterations: int = 3,
                 skip_semantic: bool = True, llm_model: str = 'gemini-3-flash-preview-nothinking',
                 llm_temperature: float = 0.2, run_layout_optimization: bool = False,
                 only_analyze: bool = False):
        """
        初始化迭代优化器
        
        Args:
            data_dir: 数据目录（包含子目录，每个子目录有布局和协议文件）
            max_iterations: 最大迭代次数
            robot_radius: 机器人半径（米）
            min_gap: 最小通行间距（米）
            layout_workers: 布局优化的并行worker数量
            layout_max_iterations: 布局优化的最大迭代次数
            skip_semantic: 是否跳过语义评估（快速模式）
            llm_model: LLM模型名称
            llm_temperature: LLM温度参数
            run_layout_optimization: 是否在应用调整后运行布局优化器（默认False，因为_is_move_safe已确保无违规）
            only_analyze: 仅分析模式，只计算可达性指标，不应用调整，不进行优化
        """
        self.data_dir = Path(data_dir)
        self.max_iterations = max_iterations
        self.robot_radius = robot_radius
        self.min_gap = min_gap
        self.layout_workers = layout_workers
        self.layout_max_iterations = layout_max_iterations
        self.skip_semantic = skip_semantic
        self.llm_model = llm_model
        self.llm_temperature = llm_temperature
        self.run_layout_optimization = run_layout_optimization
        self.only_analyze = only_analyze
        
        # 工作目录
        self.work_dir = Path(__file__).parent
        self.output_dir = self.work_dir / "output"
        self.iteration_dir = self.work_dir / "iterations"
        
        # 脚本路径
        self.nav_optimizer_script = self.work_dir / "navigation_optimizer.py"
        self.layout_optimizer_script = self.work_dir.parent / "batch_optimize_layouts_parallel.py"
        self.assets_json = self.work_dir.parent / "assets_annotated.json"
        
    def identify_platform_mapping(self, layout_data: dict) -> Dict[str, List[int]]:
        """
        识别哪些物品在哪个平台上
        
        Args:
            layout_data: 布局JSON数据
            
        Returns:
            平台ID -> 物品索引列表的映射
        """
        platform_items = {}
        unmatched_items = []  # 记录未匹配的物品
        
        for idx, obj in enumerate(layout_data['objects']):
            initial_location = obj.get('initial_location', '')
            
            # 跳过floor和空的initial_location
            if not initial_location or initial_location == 'floor':
                continue
            
            obj_id = obj.get('id', f'Object[{idx}]')
            
            # 规范化平台名称（转小写，去除下划线）
            normalized_location = initial_location.lower().replace('_', '').replace('-', '')
            
            # 查找对应的平台物体
            platform_id = None
            for platform_obj in layout_data['objects']:
                platform_obj_id = platform_obj.get('id', '')
                normalized_platform_id = platform_obj_id.lower().replace('_', '').replace('-', '')
                
                if normalized_location in normalized_platform_id or \
                   normalized_platform_id in normalized_location:
                    platform_id = platform_obj_id
                    break
            
            if platform_id:
                if platform_id not in platform_items:
                    platform_items[platform_id] = []
                platform_items[platform_id].append(idx)
            else:
                # 记录未匹配的物品
                unmatched_items.append({
                    'index': idx,
                    'id': obj_id,
                    'initial_location': initial_location
                })
        
        # 打印调试信息
        if unmatched_items:
            print(f"    ⚠️ 警告：{len(unmatched_items)} 个桌面物体未找到对应平台：")
            for item in unmatched_items[:5]:  # 只显示前5个
                print(f"      - {item['id']} (initial_location: {item['initial_location']})")
            if len(unmatched_items) > 5:
                print(f"      ... 还有 {len(unmatched_items) - 5} 个")
        
        # 打印匹配统计
        total_desktop_items = sum(len(items) for items in platform_items.values())
        print(f"    📊 平台-物品映射: {len(platform_items)} 个平台, {total_desktop_items} 个桌面物体")
        for platform_id, item_indices in platform_items.items():
            print(f"      - {platform_id}: {len(item_indices)} 个物体")
        
        return platform_items
    
    def apply_rotation_fixes(self, layout_file: Path, rotation_fixes: List[dict]) -> bool:
        """
        应用旋转修复（针对面向墙面的设备），并同步旋转平台上的物品
        
        Args:
            layout_file: 布局文件路径
            rotation_fixes: 旋转修复列表
            
        Returns:
            是否成功应用修复
        """
        if not rotation_fixes:
            return False
        
        import math
        
        # 读取布局文件
        with open(layout_file, 'r', encoding='utf-8') as f:
            layout_data = json.load(f)
        
        # 识别平台-物品映射
        platform_items = self.identify_platform_mapping(layout_data)
        
        total_fixes = 0
        
        # 应用每个旋转修复
        for fix in rotation_fixes:
            obj_id = fix.get('object_id')
            suggested_rotation = fix.get('suggested_rotation')
            
            if not obj_id or suggested_rotation is None:
                continue
            
            # 查找物体
            obj_index = None
            for idx, obj in enumerate(layout_data['objects']):
                if obj.get('id') == obj_id:
                    obj_index = idx
                    break
            
            if obj_index is None:
                print(f"    警告: 未找到物体 {obj_id}")
                continue
            
            # 应用旋转
            obj = layout_data['objects'][obj_index]
            current_rotation = obj.get('rotation', {}).get('z', 0)
            rotation_delta = suggested_rotation - current_rotation
            
            obj.setdefault('rotation', {})['z'] = suggested_rotation
            
            total_fixes += 1
            print(f"    修复旋转 {obj_id}: {current_rotation:.1f}° → {suggested_rotation:.1f}° (面向房间内)")
            
            # 同步旋转平台上的物品（保持相对位置）
            if obj_id in platform_items:
                item_indices = platform_items[obj_id]
                platform_center = obj['position']
                cx, cy = platform_center['x'], platform_center['y']
                
                # 旋转角度（弧度）
                theta = math.radians(rotation_delta)
                cos_theta = math.cos(theta)
                sin_theta = math.sin(theta)
                
                for item_idx in item_indices:
                    item = layout_data['objects'][item_idx]
                    item_id = item.get('id', f'Object[{item_idx}]')
                    
                    # 物品当前位置
                    ix, iy = item['position']['x'], item['position']['y']
                    
                    # 计算相对于平台中心的向量
                    dx = ix - cx
                    dy = iy - cy
                    
                    # 旋转向量
                    dx_new = dx * cos_theta - dy * sin_theta
                    dy_new = dx * sin_theta + dy * cos_theta
                    
                    # 计算新的世界坐标
                    item['position']['x'] = cx + dx_new
                    item['position']['y'] = cy + dy_new
                    
                    # 同步旋转物品自身的角度
                    item_current_rot = item.get('rotation', {}).get('z', 0)
                    item.setdefault('rotation', {})['z'] = (item_current_rot + rotation_delta) % 360
                    
                    print(f"      └─ 同步旋转 {item_id}: 位置 ({ix:.3f}, {iy:.3f}) → ({cx + dx_new:.3f}, {cy + dy_new:.3f}), "
                          f"角度 {item_current_rot:.1f}° → {(item_current_rot + rotation_delta) % 360:.1f}°")
        
        # 保存修改后的布局
        if total_fixes > 0:
            with open(layout_file, 'w', encoding='utf-8') as f:
                json.dump(layout_data, f, indent=2, ensure_ascii=False)
            print(f"    成功应用 {total_fixes} 个旋转修复（含桌面物品同步旋转）")
            return True
        
        return False
    
    def apply_adjustments_to_layout(self, layout_file: Path, 
                                    adjustments: List[dict]) -> bool:
        """
        将调整应用到布局文件（包括同步移动平台上的物品）
        
        Args:
            layout_file: 布局文件路径
            adjustments: 调整列表
            
        Returns:
            是否成功应用调整
        """
        if not adjustments:
            print(f"    无需调整")
            return False
        
        # 读取布局文件
        with open(layout_file, 'r', encoding='utf-8') as f:
            layout_data = json.load(f)
        
        # 识别平台-物品映射
        platform_items = self.identify_platform_mapping(layout_data)
        
        # 记录已调整的物体
        adjusted_objects = set()
        total_adjustments = 0
        
        # 应用每个调整
        for adj in adjustments:
            obj_id = adj.get('object')
            direction = adj.get('direction')
            distance = adj.get('distance')
            
            if not obj_id or not direction or distance is None:
                continue
            
            # 查找物体
            obj_index = None
            for idx, obj in enumerate(layout_data['objects']):
                if obj.get('id') == obj_id:
                    obj_index = idx
                    break
            
            if obj_index is None:
                print(f"    警告: 未找到物体 {obj_id}")
                continue
            
            # 应用调整
            obj = layout_data['objects'][obj_index]
            if direction == 'x':
                obj['position']['x'] += distance
            elif direction == 'y':
                obj['position']['y'] += distance
            else:
                print(f"    警告: 未知方向 {direction}")
                continue
            
            adjusted_objects.add(obj_id)
            total_adjustments += 1
            
            print(f"    调整 {obj_id}: {direction} {distance:+.3f}m")
            
            # 同步移动平台上的物品
            if obj_id in platform_items:
                item_indices = platform_items[obj_id]
                for item_idx in item_indices:
                    item = layout_data['objects'][item_idx]
                    item_id = item.get('id', f'Object[{item_idx}]')
                    
                    if direction == 'x':
                        item['position']['x'] += distance
                    elif direction == 'y':
                        item['position']['y'] += distance
                    
                    print(f"      └─ 同步移动 {item_id}: {direction} {distance:+.3f}m")
        
        # 保存修改后的布局
        if total_adjustments > 0:
            with open(layout_file, 'w', encoding='utf-8') as f:
                json.dump(layout_data, f, indent=2, ensure_ascii=False)
            print(f"    成功应用 {total_adjustments} 个调整")
            return True
        
        return False
    
    def collect_rotation_fixes(self, subdir: Path) -> List[dict]:
        """
        从导航分析结果中收集旋转修复建议
        
        Args:
            subdir: 子目录路径
            
        Returns:
            所有旋转修复建议的列表
        """
        result_file = self.output_dir / subdir.name / "navigation_analysis_results.json"
        
        if not result_file.exists():
            return []
        
        with open(result_file, 'r', encoding='utf-8') as f:
            results = json.load(f)
        
        # 提取旋转修复（存储在元数据中）
        rotation_fixes = results.get('_rotation_fixes', [])
        return rotation_fixes
    
    def collect_all_adjustments(self, subdir: Path) -> List[dict]:
        """
        从导航分析结果中收集所有调整建议
        
        Args:
            subdir: 子目录路径
            
        Returns:
            所有调整建议的列表
        """
        result_file = self.output_dir / subdir.name / "navigation_analysis_results.json"
        
        if not result_file.exists():
            return []
        
        with open(result_file, 'r', encoding='utf-8') as f:
            results = json.load(f)
        
        all_adjustments = []
        for path_key, path_result in results.items():
            # 跳过元数据键
            if path_key.startswith('_'):
                continue
            if not path_result.get('reachable', True):
                adjustments = path_result.get('adjustments', [])
                all_adjustments.extend(adjustments)
        
        # 去重：同一个物体的同一方向只保留距离最大的调整
        unique_adjustments = {}
        for adj in all_adjustments:
            obj_id = adj.get('object')
            direction = adj.get('direction')
            distance = adj.get('distance')
            
            key = (obj_id, direction)
            if key not in unique_adjustments:
                unique_adjustments[key] = adj
            else:
                # 保留距离绝对值更大的调整
                if abs(distance) > abs(unique_adjustments[key]['distance']):
                    unique_adjustments[key] = adj
        
        return list(unique_adjustments.values())
    
    def run_navigation_analysis(self, iteration: int) -> bool:
        """
        运行导航分析
        
        Args:
            iteration: 当前迭代次数
            
        Returns:
            是否成功
        """
        print(f"\n{'='*80}")
        print(f"迭代 {iteration}: 运行导航分析")
        print(f"{'='*80}")
        
        cmd = [
            'python3',
            str(self.nav_optimizer_script),
            '--data-dir', str(self.data_dir),
            '--output-dir', str(self.output_dir),
            '--assets', str(self.assets_json)
        ]
        
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(result.stdout)
            return True
        except subprocess.CalledProcessError as e:
            print(f"导航分析失败: {e}")
            print(e.stderr)
            return False
    
    def run_layout_optimization_step(self, iteration: int) -> bool:
        """
        运行布局优化步骤
        
        Args:
            iteration: 当前迭代次数
            
        Returns:
            是否成功
        """
        print(f"\n{'='*80}")
        print(f"迭代 {iteration}: 运行布局优化")
        print(f"{'='*80}")
        
        # 创建迭代输出目录
        iter_output_dir = self.iteration_dir / f"iteration_{iteration}"
        iter_output_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            'python3',
            str(self.layout_optimizer_script),
            '--input-dir', str(self.data_dir),
            '--output-dir', str(iter_output_dir),
            '--workers', str(self.layout_workers),
            '--max-iterations', str(self.layout_max_iterations),
            '--model', self.llm_model,
            '--temperature', str(self.llm_temperature),
        ]
        
        # 根据配置添加快速模式标志
        if self.skip_semantic:
            cmd.append('--skip-semantic')  # 快速模式，只优化物理约束
        
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(result.stdout)
            
            # 将优化后的布局复制回数据目录
            self._copy_optimized_layouts_back(iter_output_dir)
            return True
        except subprocess.CalledProcessError as e:
            print(f"布局优化失败: {e}")
            print(e.stderr)
            return False
    
    def _copy_optimized_layouts_back(self, iter_output_dir: Path):
        """
        将优化后的布局复制回数据目录
        
        Args:
            iter_output_dir: 迭代输出目录
        """
        print(f"\n复制优化后的布局回数据目录...")
        
        for subdir in iter_output_dir.iterdir():
            if not subdir.is_dir():
                continue
            
            # 查找优化后的布局文件（支持两种格式）
            layout_files = list(subdir.glob("*_room_isaacsim.json"))
            if not layout_files:
                layout_files = list(subdir.glob("*_optimized.json"))
            if not layout_files:
                continue
            
            optimized_layout = layout_files[0]
            
            # 找到原始数据目录中的对应子目录
            for orig_subdir in self.data_dir.iterdir():
                if not orig_subdir.is_dir():
                    continue
                
                if subdir.name in orig_subdir.name or orig_subdir.name in subdir.name:
                    # 找到原始布局文件（支持两种格式）
                    orig_layout_files = list(orig_subdir.glob("*_room_isaacsim.json"))
                    if not orig_layout_files:
                        orig_layout_files = list(orig_subdir.glob("*_optimized.json"))
                    if orig_layout_files:
                        orig_layout = orig_layout_files[0]
                        # 备份原始文件
                        backup_file = orig_layout.with_suffix('.json.bak')
                        shutil.copy2(orig_layout, backup_file)
                        # 复制优化后的文件
                        shutil.copy2(optimized_layout, orig_layout)
                        print(f"  ✓ {orig_subdir.name}")
                    break
    
    def _run_analysis_only(self):
        """仅分析模式：只运行导航分析并生成可达性报告"""
        print(f"\n{'='*80}")
        print(f"运行导航可达性分析...")
        print(f"{'='*80}")
        
        # 运行导航分析
        if not self.run_navigation_analysis(1):
            print(f"导航分析失败")
            return
        
        # 计算收敛指标
        unreachable, total, rate = self.calculate_convergence_metrics()
        
        # 生成详细报告
        print(f"\n{'='*80}")
        print(f"导航可达性分析报告")
        print(f"{'='*80}")
        print(f"总体指标:")
        print(f"  总路径数: {total}")
        print(f"  可达路径: {total - unreachable} ({100-rate:.1f}%)")
        print(f"  不可达路径: {unreachable} ({rate:.1f}%)")
        print(f"\n结果评估:")
        if rate == 0:
            print(f"  ✓ 优秀：所有路径都可达")
        elif rate < 10:
            print(f"  ✓ 良好：大部分路径可达")
        elif rate < 30:
            print(f"  ⚠ 中等：需要优化")
        else:
            print(f"  ✗ 较差：严重需要优化")
        
        # 详细的不可达路径报告
        if unreachable > 0:
            print(f"\n{'='*80}")
            print(f"不可达路径详情:")
            print(f"{'='*80}")
            
            unreachable_paths = []
            for result_file in self.output_dir.rglob("navigation_analysis_results.json"):
                try:
                    with open(result_file, 'r', encoding='utf-8') as f:
                        results = json.load(f)
                    
                    experiment_name = result_file.parent.name
                    for path_key, path_result in results.items():
                        if not path_result.get('reachable', True):
                            unreachable_paths.append({
                                'experiment': experiment_name,
                                'path': path_key,
                                'adjustments': path_result.get('adjustments', [])
                            })
                except Exception as e:
                    print(f"警告: 读取结果文件失败 {result_file}: {e}")
            
            # 按实验分组显示
            experiments = {}
            for path_info in unreachable_paths:
                exp_name = path_info['experiment']
                if exp_name not in experiments:
                    experiments[exp_name] = []
                experiments[exp_name].append(path_info)
            
            for exp_name, paths in experiments.items():
                print(f"\n实验: {exp_name}")
                print(f"  不可达路径数: {len(paths)}")
                for path_info in paths:
                    print(f"    - {path_info['path']}")
                    if path_info['adjustments']:
                        print(f"      建议调整:")
                        for adj in path_info['adjustments']:
                            obj = adj.get('object', '?')
                            direction = adj.get('direction', '?')
                            distance = adj.get('distance', 0)
                            print(f"        • {obj}: {direction}方向 {distance:+.3f}m")
        
        # 保存分析报告
        report_file = self.work_dir / f"reachability_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'config': {
                'data_dir': str(self.data_dir),
                'robot_radius': self.robot_radius,
                'min_gap': self.min_gap
            },
            'metrics': {
                'total_paths': total,
                'reachable_paths': total - unreachable,
                'unreachable_paths': unreachable,
                'reachable_rate': 100 - rate,
                'unreachable_rate': rate
            },
            'unreachable_details': unreachable_paths
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'='*80}")
        print(f"分析完成")
        print(f"{'='*80}")
        print(f"详细报告已保存到: {report_file}")
        print(f"\n输出目录:")
        print(f"  导航分析结果: {self.output_dir}")
        print(f"  可达性报告: {report_file}")
    
    def calculate_convergence_metrics(self) -> Tuple[int, int, float]:
        """
        计算收敛指标
        
        Returns:
            (不可达路径数, 总路径数, 不可达率)
        """
        total_unreachable = 0
        total_paths = 0
        
        for result_file in self.output_dir.rglob("navigation_analysis_results.json"):
            try:
                with open(result_file, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                
                for path_key, path_result in results.items():
                    total_paths += 1
                    if not path_result.get('reachable', True):
                        total_unreachable += 1
            except Exception as e:
                print(f"警告: 读取结果文件失败 {result_file}: {e}")
        
        unreachable_rate = (total_unreachable / total_paths * 100) if total_paths > 0 else 0
        return total_unreachable, total_paths, unreachable_rate
    
    def run_iterative_optimization(self):
        """运行迭代优化"""
        print(f"\n{'='*80}")
        print(f"{'开始导航可达性分析' if self.only_analyze else '开始导航迭代优化'}")
        print(f"{'='*80}")
        print(f"导航参数:")
        print(f"  数据目录: {self.data_dir}")
        print(f"  最大迭代次数: {self.max_iterations if not self.only_analyze else 1}")
        print(f"  机器人半径: {self.robot_radius}m")
        print(f"  最小通行间距: {self.min_gap}m")
        print(f"  运行模式: {'仅分析（不优化）' if self.only_analyze else '分析+优化'}")
        
        if not self.only_analyze:
            print(f"布局优化:")
            print(f"  启用布局优化: {'是' if self.run_layout_optimization else '否（默认，保持化学约束）'}")
            if self.run_layout_optimization:
                print(f"  并行Workers: {self.layout_workers}")
                print(f"  最大迭代次数: {self.layout_max_iterations}")
                print(f"  优化模式: {'快速模式（物理约束）' if self.skip_semantic else '完整模式（含语义评估）'}")
                print(f"  LLM模型: {self.llm_model}")
                print(f"  LLM温度: {self.llm_temperature}")
        
        # 创建必要的目录
        self.output_dir.mkdir(exist_ok=True)
        self.iteration_dir.mkdir(exist_ok=True)
        
        # 仅分析模式：只运行导航分析并生成报告
        if self.only_analyze:
            return self._run_analysis_only()
        
        # 记录迭代历史
        iteration_history = []
        
        for iteration in range(1, self.max_iterations + 1):
            print(f"\n{'#'*80}")
            print(f"# 迭代 {iteration}/{self.max_iterations}")
            print(f"{'#'*80}")
            
            # Step 1: 运行导航分析
            if not self.run_navigation_analysis(iteration):
                print(f"迭代 {iteration}: 导航分析失败，终止优化")
                break
            
            # Step 2: 计算收敛指标
            unreachable, total, rate = self.calculate_convergence_metrics()
            print(f"\n迭代 {iteration} 收敛指标:")
            print(f"  不可达路径: {unreachable}/{total} ({rate:.1f}%)")
            
            iteration_history.append({
                'iteration': iteration,
                'unreachable_paths': unreachable,
                'total_paths': total,
                'unreachable_rate': rate
            })
            
            # 检查是否已收敛（所有路径都可达）
            if unreachable == 0:
                print(f"\n{'='*80}")
                print(f"✓ 优化完成！所有路径都可达")
                print(f"{'='*80}")
                break
            
            # Step 3: 收集并应用调整
            print(f"\n{'='*80}")
            print(f"迭代 {iteration}: 应用导航调整")
            print(f"{'='*80}")
            
            total_adjusted = 0
            for subdir in self.data_dir.iterdir():
                if not subdir.is_dir():
                    continue
                
                # 查找布局文件（支持两种格式）
                layout_files = list(subdir.glob("*_room_isaacsim.json"))
                if not layout_files:
                    # 尝试查找优化后的布局文件
                    layout_files = list(subdir.glob("*_optimized.json"))
                if not layout_files:
                    continue
                
                layout_file = layout_files[0]
                
                # 首先收集并应用旋转修复（面向墙面的设备）
                rotation_fixes = self.collect_rotation_fixes(subdir)
                if rotation_fixes:
                    print(f"\n处理: {subdir.name}")
                    print(f"  发现 {len(rotation_fixes)} 个旋转修复建议（面向墙面的设备）")
                    self.apply_rotation_fixes(layout_file, rotation_fixes)
                
                # 然后收集并应用位置调整
                adjustments = self.collect_all_adjustments(subdir)
                
                if adjustments or rotation_fixes:
                    if adjustments:
                        if not rotation_fixes:  # 如果之前没打印过
                            print(f"\n处理: {subdir.name}")
                        print(f"  发现 {len(adjustments)} 个位置调整建议")
                        
                        # 应用位置调整
                        if self.apply_adjustments_to_layout(layout_file, adjustments):
                            total_adjusted += 1
                    elif rotation_fixes:  # 只有旋转修复，没有位置调整
                        total_adjusted += 1
            
            print(f"\n迭代 {iteration}: 共调整 {total_adjusted} 个布局")
            
            # Step 4: 运行布局优化（修复物理违规） - 可选
            if self.run_layout_optimization:
                print(f"\n{'='*80}")
                print(f"迭代 {iteration}: 运行布局优化（修复物理违规）")
                print(f"{'='*80}")
                if not self.run_layout_optimization_step(iteration):
                    print(f"迭代 {iteration}: 布局优化失败，终止优化")
                    break
            else:
                print(f"\n{'='*80}")
                print(f"迭代 {iteration}: 跳过布局优化（_is_move_safe已确保无违规）")
                print(f"{'='*80}")
            
            # 如果是最后一次迭代，再运行一次导航分析
            if iteration == self.max_iterations:
                print(f"\n{'='*80}")
                print(f"最后一次导航分析")
                print(f"{'='*80}")
                self.run_navigation_analysis(iteration + 1)
                unreachable, total, rate = self.calculate_convergence_metrics()
                print(f"\n最终收敛指标:")
                print(f"  不可达路径: {unreachable}/{total} ({rate:.1f}%)")
                
                iteration_history.append({
                    'iteration': iteration + 1,
                    'unreachable_paths': unreachable,
                    'total_paths': total,
                    'unreachable_rate': rate
                })
        
        # 保存迭代历史
        history_file = self.work_dir / f"iteration_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump({
                'config': {
                    'data_dir': str(self.data_dir),
                    'max_iterations': self.max_iterations,
                    'robot_radius': self.robot_radius,
                    'min_gap': self.min_gap
                },
                'history': iteration_history
            }, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'='*80}")
        print(f"迭代优化完成")
        print(f"{'='*80}")
        print(f"迭代历史已保存到: {history_file}")
        
        # 打印汇总
        print(f"\n迭代汇总:")
        for record in iteration_history:
            print(f"  迭代 {record['iteration']}: "
                  f"{record['unreachable_paths']}/{record['total_paths']} 不可达 "
                  f"({record['unreachable_rate']:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description='导航迭代优化器')
    parser.add_argument(
        '--data-dir',
        type=str,
        required=True,
        help='数据目录（包含子目录，每个子目录有布局和协议文件）'
    )
    parser.add_argument(
        '--max-iterations',
        type=int,
        default=5,
        help='最大迭代次数 (default: 5)'
    )
    parser.add_argument(
        '--robot-radius',
        type=float,
        default=0.3,
        help='机器人半径（米） (default: 0.3)'
    )
    parser.add_argument(
        '--min-gap',
        type=float,
        default=1.2,
        help='最小通行间距（米） (default: 1.2)'
    )
    parser.add_argument(
        '--layout-workers',
        type=int,
        default=150,
        help='布局优化的并行worker数量 (default: 150)'
    )
    parser.add_argument(
        '--layout-max-iterations',
        type=int,
        default=3,
        help='布局优化的最大迭代次数 (default: 3)'
    )
    parser.add_argument(
        '--full-semantic',
        action='store_true',
        help='启用完整语义评估（较慢，默认关闭）'
    )
    parser.add_argument(
        '--llm-model',
        type=str,
        default='gemini-3-flash-preview-nothinking',
        help='LLM模型 (default: gemini-3-flash-preview-nothinking, 可选: claude-sonnet-4-5-20250929, gpt-4o-2024-11-20等)'
    )
    parser.add_argument(
        '--llm-temperature',
        type=float,
        default=0.2,
        help='LLM温度参数 (default: 0.2, 范围: 0.0-1.0)'
    )
    parser.add_argument(
        '--enable-layout-optimization',
        action='store_true',
        help='启用布局优化步骤（默认关闭，因为_is_move_safe已确保移动不会产生违规）'
    )
    parser.add_argument(
        '--only-analyze',
        action='store_true',
        help='仅分析模式：只计算可达性指标，不应用调整，不进行优化'
    )
    
    args = parser.parse_args()
    
    # 创建优化器实例
    optimizer = IterativeNavigationOptimizer(
        data_dir=args.data_dir,
        max_iterations=args.max_iterations,
        robot_radius=args.robot_radius,
        min_gap=args.min_gap,
        layout_workers=args.layout_workers,
        layout_max_iterations=args.layout_max_iterations,
        skip_semantic=not args.full_semantic,  # 默认快速模式
        llm_model=args.llm_model,
        llm_temperature=args.llm_temperature,
        run_layout_optimization=args.enable_layout_optimization,  # 默认False
        only_analyze=args.only_analyze  # 默认False
    )
    
    # 运行迭代优化
    optimizer.run_iterative_optimization()


if __name__ == '__main__':
    main()

