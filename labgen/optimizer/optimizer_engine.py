"""
LLM 驱动的布局优化主引擎
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from labgen.optimizer.config import OPTIMIZER_CONFIG
from labgen.optimizer.evaluation_runner import EvaluationRunner
from labgen.optimizer.summarizer import EvaluationSummarizer
from labgen.optimizer.llm_agent import LLMAgent
from labgen.optimizer.layout_editor import LayoutEditor
from labtouchstone.evaluator.utils.asset_loader import AssetLoader

logger = logging.getLogger(__name__)


@dataclass
class IterationRecord:
    iteration: int
    score: float
    violation_count: int
    adjustments: List[Dict] = field(default_factory=list)
    evaluation_report_path: Optional[Path] = None


class LLMOptimizerEngine:
    """基于 LLM 与评估反馈的迭代优化引擎"""

    def __init__(
        self,
        layout_path: Path,
        protocol_path: Path,
        working_dir: Path,
        asset_library_path: Path,
    ) -> None:
        self.layout_path = layout_path.resolve()
        self.protocol_path = protocol_path.resolve()
        self.working_dir = working_dir.resolve()
        self.working_dir.mkdir(parents=True, exist_ok=True)

        with self.layout_path.open("r", encoding="utf-8") as f:
            self.layout_data = json.load(f)

        with self.protocol_path.open("r", encoding="utf-8") as f:
            self.protocol_data = json.load(f)

        with asset_library_path.open("r", encoding="utf-8") as f:
            self.asset_library = json.load(f)

        # 创建 AssetLoader 用于坐标转换
        self.asset_loader = AssetLoader(str(asset_library_path))

        self.evaluation_runner = EvaluationRunner()
        self.llm_agent = LLMAgent(asset_library=self.asset_library)  # 传递资产库
        self.iterations: List[IterationRecord] = []

        self.best_layout = json.loads(json.dumps(self.layout_data))
        self.best_score = float("-inf")
        self.best_violation_count = 9999

    def _write_layout(self, data: Dict) -> None:
        with self.layout_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _get_protocol_location_guidance(self) -> Dict[str, str]:
        """
        从 Protocol 中提取资产的建议位置
        
        Returns:
            资产名称到建议位置的映射 {asset_name: recommended_location}
        """
        protocol_locations = {}
        if 'assets' in self.protocol_data:
            for asset in self.protocol_data['assets']:
                asset_name = asset.get('name')
                initial_loc = asset.get('initial_location')
                if asset_name and initial_loc and initial_loc != 'floor':
                    protocol_locations[asset_name] = initial_loc
        
        return protocol_locations
    

    def _assign_reagent_shelf_height(self, obj_id: str, obj: Dict) -> float:
        """
        根据化学属性智能分配试剂柜层级
        
        分层策略（4层，考虑不相容性分离）：
        - 0.8m（底层）：酸类（重质，腐蚀性，需隔离）
        - 1.1m（中下层）：碱类（与酸分离，防止混合）
        - 1.3m（中上层）：易燃易爆、氧化剂、活泼金属（远离酸碱）
        - 1.5m（顶层）：一般试剂、玻璃容器、低危险性物质
        
        不相容性原则：
        - 酸 ⇆ 碱：分开放置（0.8m vs 1.1m）
        - 易燃物 ⇆ 氧化剂：都在1.3m但已远离酸碱
        - 活泼金属 ⇆ 水/酸：分离（1.3m vs 0.8m）
        
        Args:
            obj_id: 物体ID
            obj: 物体数据字典
            
        Returns:
            分配的高度（m）
        """
        # 获取化学属性
        asset_name = obj_id.split('_')[0] if '_' in obj_id else obj_id
        
        # 从资产库查找化学属性
        # asset_library是一个字典，包含'assets'键
        assets_list = self.asset_library.get('assets', [])
        asset_info = next((a for a in assets_list if a.get('id') == asset_name or a.get('name') == asset_name), None)
        
        if not asset_info:
            # 如果找不到资产信息，默认顶层（最安全）
            logger.debug(f"未找到 {asset_name} 的资产信息，使用默认高度 1.5m")
            return 1.5
        
        props = asset_info.get('props', {})
        
        # 分层逻辑（按优先级检查）
        
        # 第1层 0.8m：酸类（底层，重质，与碱隔离）
        if props.get('acid'):
            logger.debug(f"{asset_name} 是酸类 → 0.8m（底层）")
            return 0.8
        
        # 第2层 1.1m：碱类（与酸分离）
        if props.get('base'):
            logger.debug(f"{asset_name} 是碱类 → 1.1m（与酸分离）")
            return 1.1
        
        # 第3层 1.3m：易燃易爆、氧化剂、活泼金属（远离酸碱）
        if props.get('flammable') or props.get('explosive') or props.get('oxidizer') or props.get('reactive_metal'):
            logger.debug(f"{asset_name} 是易燃/氧化剂/活泼金属 → 1.3m（远离酸碱）")
            return 1.3
        
        # 第4层 1.5m：一般试剂、玻璃容器、有毒但不属于上述类别的物质
        logger.debug(f"{asset_name} 是一般试剂 → 1.5m（顶层）")
        return 1.5

    def _record_iteration(
        self,
        iteration: int,
        evaluation: Dict,
        adjustments: List[Dict],
        report_dir: Path,
    ) -> IterationRecord:
        scores = evaluation.get("scores", {})
        total_score = scores.get("total", 0.0)
        summarizer = EvaluationSummarizer(evaluation)
        violation_count = summarizer.violation_count()
        report_files = sorted((report_dir / "evaluation").glob("*_evaluation_report.json"))
        report_path = report_files[-1] if report_files else None

        record = IterationRecord(
            iteration=iteration,
            score=total_score,
            violation_count=violation_count,
            adjustments=adjustments,
            evaluation_report_path=report_path,
        )
        self.iterations.append(record)
        return record

    def _check_room_asset_constraints(self, layout: Dict) -> Tuple[float, List[Dict], bool]:
        """
        检查房间资产约束是否满足
        
        Args:
            layout: 布局JSON数据
        
        Returns:
            (score, violations, is_satisfied):
            - score: 房间资产约束得分（0-6分）
            - violations: 违规列表
            - is_satisfied: 是否满足约束（score == 6.0 且 violations == []）
        """
        # 临时写入布局文件用于评估
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(layout, f, indent=2, ensure_ascii=False)
            temp_layout_path = Path(f.name)
        
        try:
            # 运行快速评估（只检查物理约束，跳过USD生成和渲染）
            temp_working_dir = Path(tempfile.mkdtemp())
            try:
                evaluation = self.evaluation_runner.run_full_pipeline(
                    temp_layout_path,
                    self.protocol_path,
                    temp_working_dir,
                    skip_semantic=True,  # 快速模式，跳过USD和渲染
                )
                
                # 提取房间资产约束结果
                physical_constraints = evaluation.get('physical_evaluation', {}).get('physical_constraints', {})
                room_result = physical_constraints.get('room_assets', {})
                
                score = room_result.get('score', 0.0)
                violations = room_result.get('violations', [])
                is_satisfied = (score >= 6.0 and len(violations) == 0)
                
                return score, violations, is_satisfied
            finally:
                # 清理临时目录
                import shutil
                if temp_working_dir.exists():
                    shutil.rmtree(temp_working_dir, ignore_errors=True)
        finally:
            # 清理临时布局文件
            if temp_layout_path.exists():
                temp_layout_path.unlink()

    def _is_converged(self) -> bool:
        if len(self.iterations) < 2:
            return False

        recent = self.iterations[-OPTIMIZER_CONFIG["no_improvement_rounds"] :]
        if len(recent) < OPTIMIZER_CONFIG["no_improvement_rounds"]:
            return False

        scores = [rec.score for rec in recent]
        violations = [rec.violation_count for rec in recent]

        score_improvement = max(scores) - min(scores)
        violation_reduction = max(violations) - min(violations)

        logger.info(
            "近期改进: 分数Δ=%.2f, 违规Δ=%d",
            score_improvement,
            violation_reduction,
        )

        return (
            score_improvement < OPTIMIZER_CONFIG["score_improvement_threshold"]
            and violation_reduction < OPTIMIZER_CONFIG["violation_reduction_threshold"]
        )

    def optimize(self) -> Dict:
        logger.info("开始 LLM 指导的两阶段优化流程（先房间资产，后桌面物体）")

        current_layout = self.layout_data

        # 阶段1: 优化房间资产
        logger.info("=" * 80)
        logger.info("阶段1: 优化房间资产（floor objects）")
        logger.info("=" * 80)
        current_layout = self._optimize_phase(current_layout, "room", "Phase1_Room")
        
        # 阶段2: 优化桌面物体
        logger.info("=" * 80)
        logger.info("阶段2: 优化桌面物体（desktop objects）")
        logger.info("=" * 80)
        current_layout = self._optimize_phase(current_layout, "desktop", "Phase2_Desktop")
        
        logger.info("=" * 80)
        logger.info("两阶段优化完成")
        logger.info("最佳得分: %.2f, 最佳违规数: %d", self.best_score, self.best_violation_count)
        logger.info("=" * 80)
        
        return self._generate_summary()

    def _optimize_phase(self, initial_layout: Dict, optimize_mode: str, phase_prefix: str) -> Dict:
        """
        单阶段优化
        
        Args:
            initial_layout: 初始布局
            optimize_mode: 'room' 或 'desktop'
            phase_prefix: 阶段前缀，用于目录命名
        
        Returns:
            优化后的布局
        """
        current_layout = json.loads(json.dumps(initial_layout))  # 深拷贝
        phase_best_layout = json.loads(json.dumps(initial_layout))  # 此阶段的最佳布局
        phase_best_score = float("-inf")
        phase_best_violations = 9999
        phase_iterations = 0
        max_phase_iterations = OPTIMIZER_CONFIG["max_iterations"]
        consecutive_rejects = 0  # 连续拒绝次数
        
        # 如果是房间资产优化阶段，先检查约束是否已满足
        if optimize_mode == "room":
            logger.info("检查房间资产约束状态...")
            score, violations, is_satisfied = self._check_room_asset_constraints(current_layout)
            logger.info("房间资产约束得分: %.2f/6.0, 违规数: %d", score, len(violations))
            
            if is_satisfied:
                logger.info("✓ 房间资产约束已满足（得分 %.2f/6.0，无违规），跳过房间资产优化阶段", score)
                return current_layout
            else:
                logger.info("房间资产约束未满足，开始优化（目标：边界3分+碰撞3分=6分）")
        
        for iteration in range(1, max_phase_iterations + 1):
            phase_iterations += 1
            global_iteration = len(self.iterations) + 1
            
            logger.info("==== %s - 迭代 %d (全局迭代 %d) ====", phase_prefix, iteration, global_iteration)
            iteration_dir = self.working_dir / f"iteration_{global_iteration:02d}_{phase_prefix}"
            iteration_dir.mkdir(parents=True, exist_ok=True)

            # 将当前布局保存到迭代文件夹（不覆盖原文件）
            iteration_layout_path = iteration_dir / f"layout_iter_{global_iteration:02d}.json"
            with iteration_layout_path.open("w", encoding="utf-8") as f:
                json.dump(current_layout, f, indent=2, ensure_ascii=False)
            
            # 同时写入到原文件路径（用于评估器读取）
            self._write_layout(current_layout)

            # 运行评估（根据配置决定是否跳过语义评估）
            skip_semantic = OPTIMIZER_CONFIG.get("skip_semantic_evaluation", False)
            evaluation = self.evaluation_runner.run_full_pipeline(
                self.layout_path,
                self.protocol_path,
                iteration_dir,
                skip_semantic=skip_semantic,
            )
            summarizer = EvaluationSummarizer(evaluation)
            summary_text = summarizer.build_summary()
            logger.info("评估摘要:\n%s", summary_text)

            # 记录当前结果
            record = self._record_iteration(
                global_iteration,
                evaluation,
                adjustments=[],
                report_dir=iteration_dir,
            )

            # 更新最佳布局（优先选择违规数更少的，其次选择分数更高的，分数相同时选择最新的）
            is_better = False
            if record.violation_count < self.best_violation_count:
                is_better = True
            elif record.violation_count == self.best_violation_count and record.score >= self.best_score:
                # 分数相同或更高时都更新（相同时选择最新布局，因为可能满足了更多优化建议）
                is_better = True
            
            # 注意：此时评估的是应用上一次调整后的布局
            # 不在这里更新best_layout和phase_best，而是在应用新调整后重新评估并更新
            logger.info("当前布局（应用上次调整后）评估: 分数 %.2f, 违规 %d", record.score, record.violation_count)

            # === 新增：自动修复逻辑 ===
            # 尝试应用自动修复指令（支持房间资产和桌面物体阶段）
            auto_fixes = evaluation.get('improvement_suggestions', {}).get('auto_fixes', [])
            auto_fix_report = None
            
            if auto_fixes:
                logger.info(f"发现 {len(auto_fixes)} 个可自动修复的违规")
                
                # 分阶段渐进式修复：先边界后碰撞，迭代直到收敛
                current_layout, auto_fix_report = self._apply_progressive_fixes(
                    current_layout, 
                    evaluation, 
                    record.violation_count,
                    iteration_dir,
                    optimize_mode=optimize_mode
                )
                
                # 重新评估修复后的布局，更新摘要
                self._write_layout(current_layout)
                evaluation = self.evaluation_runner.run_full_pipeline(
                    self.layout_path,
                    self.protocol_path,
                    iteration_dir / "after_auto_fix",
                    skip_semantic=skip_semantic,
                )
                summarizer = EvaluationSummarizer(evaluation)
                summary_text = summarizer.build_summary(auto_fix_report=auto_fix_report)
                logger.info("修复后评估摘要:\n%s", summary_text)

            # 如果是房间资产优化阶段，检查是否已达到满足状态
            if optimize_mode == "room":
                room_score, room_violations, room_satisfied = self._check_room_asset_constraints(current_layout)
                if room_satisfied:
                    logger.info("✓ 房间资产约束已满足（得分 %.2f/6.0，无违规），提前结束优化", room_score)
                    break
            
            # 收敛判定（评估后立即判断，避免多余迭代）
            if iteration > 1 and self._is_converged():
                logger.info("%s 达到收敛条件，结束此阶段", phase_prefix)
                break

            # 调用 LLM 获取调整（传递自动化修复信息和 protocol 位置指导）
            protocol_guidance = self._get_protocol_location_guidance() if optimize_mode == "desktop" else None
            try:
                adjustments = self.llm_agent.request_adjustments(
                    current_layout, summary_text, optimize_mode, 
                    auto_fix_report=auto_fix_report,
                    protocol_location_guidance=protocol_guidance
                )
            except ValueError as exc:
                logger.error("LLM 调用失败: %s", exc)
                break
            except Exception as exc:
                # 处理API内容审核等错误
                error_str = str(exc)
                if '内容违规' in error_str or 'sensitive_words' in error_str:
                    logger.warning("⚠ LLM API内容审核误判，跳过LLM优化（自动修复已生效）")
                    logger.warning("   错误详情: %s", error_str[:200])
                    # 内容审核误判时，继续使用当前布局（自动修复可能已经生效）
                    break
                else:
                    logger.error("LLM 调用失败: %s", exc)
                    break

            if not adjustments:
                logger.info("LLM 返回空调整，%s 结束", phase_prefix)
                break

            logger.info("LLM 建议调整 %d 个对象", len(adjustments))
            record.adjustments = adjustments
            
            # 应用调整
            editor = LayoutEditor(current_layout, asset_loader=self.asset_loader)
            editor.apply_adjustments(adjustments)
            
            # 重新保存应用调整后的布局
            with iteration_layout_path.open("w", encoding="utf-8") as f:
                json.dump(current_layout, f, indent=2, ensure_ascii=False)
            logger.info("✓ 已保存应用调整后的布局到 %s", iteration_layout_path.name)
            
            # === 关键修复：重新评估应用调整后的布局，并更新best_layout ===
            # 写入布局文件供评估器读取
            self._write_layout(current_layout)
            
            # 重新运行评估（针对应用调整后的布局）
            adjusted_evaluation = self.evaluation_runner.run_full_pipeline(
                self.layout_path,
                self.protocol_path,
                iteration_dir / "after_adjustment",
                skip_semantic=skip_semantic,
            )
            
            # 提取评估结果（不记录到iterations列表）
            adjusted_score = adjusted_evaluation.get("scores", {}).get("total", 0)
            # 使用EvaluationSummarizer计算所有类型的violations（包括boundary, collision, height等）
            adjusted_summarizer = EvaluationSummarizer(adjusted_evaluation)
            adjusted_violations = adjusted_summarizer.violation_count()
            
            logger.info("应用调整后的布局评估: 分数 %.2f, 违规 %d", adjusted_score, adjusted_violations)
            
            # 检查应用调整后的布局是否更好
            if adjusted_violations < self.best_violation_count:
                is_better_after_adjustment = True
            elif adjusted_violations == self.best_violation_count and adjusted_score >= self.best_score:
                is_better_after_adjustment = True
            else:
                is_better_after_adjustment = False
            
            # 更新best_layout（针对应用调整后的布局）
            # 注意：第一次迭代时，即使分数下降也要保留调整（因为phase_best_layout还是baseline）
            is_first_iteration = (global_iteration == 1)
            
            if is_better_after_adjustment or is_first_iteration:
                # 第一次迭代：总是保留调整（即使分数下降）
                # 后续迭代：只有更好时才保留
                if is_first_iteration:
                    logger.info("✓ 第一次迭代：保留所有调整 (分数 %.2f, 违规 %d)",
                               adjusted_score, adjusted_violations)
                else:
                    logger.info("✓ 应用调整后的布局更好: 违规 %d → %d, 分数 %.2f → %.2f",
                               self.best_violation_count, adjusted_violations,
                               self.best_score, adjusted_score)
                
                self.best_score = adjusted_score
                self.best_violation_count = adjusted_violations
                self.best_layout = json.loads(json.dumps(current_layout))
                
                # 同时更新阶段最佳
                phase_best_score = adjusted_score
                phase_best_violations = adjusted_violations
                phase_best_layout = json.loads(json.dumps(current_layout))
                
                # 更新record的实际评估结果
                record.score = adjusted_score
                record.violation_count = adjusted_violations
            else:
                # 如果应用调整后更差，执行回滚（但第一次迭代不会到这里）
                logger.info("✗ 应用调整后布局更差 (分数 %.2f, 违规 %d)，执行回滚",
                           adjusted_score, adjusted_violations)
                current_layout = json.loads(json.dumps(phase_best_layout))
                # 重新保存回滚后的布局
                with iteration_layout_path.open("w", encoding="utf-8") as f:
                    json.dump(current_layout, f, indent=2, ensure_ascii=False)
                logger.info("✓ 已回滚并保存到 %s", iteration_layout_path.name)

        logger.info("%s 优化结束，当前得分: %.2f", phase_prefix, self.best_score)
        return current_layout

    def _merge_auto_fixes(self, auto_fixes: List[Dict]) -> List[Dict]:
        """
        合并针对同一对象的多个修复指令
        
        对于同一对象的多个修复指令：
        - 边界修复：取最大的移动量
        - 碰撞修复：合并移动向量
        """
        import math
        
        # 按对象ID和位置分组
        fixes_by_object = {}
        
        for fix in auto_fixes:
            fix_type = fix.get('type')
            
            if fix_type == 'boundary_fix':
                obj_id = fix['object_id']
                old_pos = fix.get('violation', {}).get('current_position', {})
                key = (obj_id, old_pos.get('x'), old_pos.get('y'))
                
                if key not in fixes_by_object:
                    fixes_by_object[key] = []
                fixes_by_object[key].append(fix)
                
            elif fix_type == 'collision_fix':
                move_obj = fix['move_object']
                old_pos = fix.get('action', {}).get('old_position', {})
                key = (move_obj, old_pos.get('x'), old_pos.get('y'))
                
                if key not in fixes_by_object:
                    fixes_by_object[key] = []
                fixes_by_object[key].append(fix)
        
        # 合并每组修复指令
        merged_fixes = []
        
        for key, fixes in fixes_by_object.items():
            if len(fixes) == 1:
                merged_fixes.append(fixes[0])
            else:
                # 多个修复指令，需要合并
                fix_type = fixes[0].get('type')
                
                if fix_type == 'boundary_fix':
                    # 边界修复：取移动量最大的（最安全的）
                    max_fix = max(fixes, key=lambda f: abs(f.get('action', {}).get('delta', 0)))
                    merged_fixes.append(max_fix)
                    logger.info(f"  合并 {len(fixes)} 个边界修复指令 → 使用最大移动量")
                    
                elif fix_type == 'collision_fix':
                    # 碰撞修复：合并移动向量
                    obj_id = fixes[0].get('move_object')
                    old_pos = fixes[0].get('action', {}).get('old_position', {})
                    
                    # 计算所有移动向量的总和（加权平均）
                    total_dx = 0
                    total_dy = 0
                    total_weight = 0
                    max_distance = 0
                    
                    for fix in fixes:
                        action = fix.get('action', {})
                        direction = action.get('direction', {})
                        distance_m = action.get('distance_m', 0)
                        overlap = fix.get('violation', {}).get('overlap_cm2', 0)
                        
                        # 使用重叠面积作为权重（重叠越大，权重越高）
                        weight = overlap if overlap > 0 else distance_m * 100
                        
                        dx = direction.get('x', 0) * distance_m * weight
                        dy = direction.get('y', 0) * distance_m * weight
                        
                        total_dx += dx
                        total_dy += dy
                        total_weight += weight
                        max_distance = max(max_distance, distance_m)
                    
                    # 计算加权平均方向
                    if total_weight > 0:
                        avg_dx = total_dx / total_weight
                        avg_dy = total_dy / total_weight
                        avg_distance = math.sqrt(avg_dx**2 + avg_dy**2)
                        
                        # 如果加权平均方向太小（向量相互抵消），使用最大距离和平均方向
                        if avg_distance < max_distance * 0.3:  # 如果平均距离小于最大距离的30%，说明向量相互抵消
                            # 计算平均方向（不考虑距离）
                            avg_dir_x = 0
                            avg_dir_y = 0
                            for fix in fixes:
                                direction = fix.get('action', {}).get('direction', {})
                                avg_dir_x += direction.get('x', 0)
                                avg_dir_y += direction.get('y', 0)
                            norm = math.sqrt(avg_dir_x**2 + avg_dir_y**2)
                            if norm > 0:
                                avg_dir_x /= norm
                                avg_dir_y /= norm
                            else:
                                # 如果方向也相互抵消，使用第一个修复的方向
                                first_dir = fixes[0].get('action', {}).get('direction', {})
                                avg_dir_x = first_dir.get('x', 1.0)
                                avg_dir_y = first_dir.get('y', 0.0)
                            
                            dir_x = avg_dir_x
                            dir_y = avg_dir_y
                            final_distance = max_distance * 1.2  # 使用最大距离的1.2倍，确保足够远
                        else:
                            # 归一化加权平均方向
                            dir_x = avg_dx / avg_distance
                            dir_y = avg_dy / avg_distance
                            final_distance = max(avg_distance, max_distance * 0.9)  # 取平均和最大值中的较大者
                        
                        new_position = {
                            'x': round(old_pos.get('x', 0) + dir_x * final_distance, 3),
                            'y': round(old_pos.get('y', 0) + dir_y * final_distance, 3),
                            'z': old_pos.get('z', 0)
                        }
                        
                        merged_fix = {
                            'type': 'collision_fix',
                            'priority': fixes[0].get('priority', 2),
                            'move_object': obj_id,
                            'fixed_object': 'multiple',  # 标记为多个对象
                            'violation': {
                                'overlap_cm2': max(f.get('violation', {}).get('overlap_cm2', 0) for f in fixes)
                            },
                            'action': {
                                'old_position': old_pos.copy(),
                                'new_position': new_position,
                                'direction': {'x': dir_x, 'y': dir_y},
                                'distance_m': final_distance
                            },
                            'description': f'移动 {obj_id} 远离多个对象（合并 {len(fixes)} 个修复指令，移动 {final_distance*100:.1f}cm）'
                        }
                        
                        merged_fixes.append(merged_fix)
                        logger.info(f"  合并 {len(fixes)} 个碰撞修复指令 → 综合移动方向 ({dir_x:.2f}, {dir_y:.2f}) 距离 {final_distance*100:.1f}cm")
                    else:
                        # 如果权重为0，使用第一个修复指令
                        merged_fixes.append(fixes[0])
        
        return merged_fixes
    
    def _apply_progressive_fixes(
        self, 
        initial_layout: Dict, 
        initial_evaluation: Dict,
        initial_violation_count: int,
        iteration_dir: Path,
        optimize_mode: str = "desktop"
    ) -> Tuple[Dict, Dict]:
        """
        分阶段渐进式修复：先边界后碰撞，迭代直到收敛
        
        策略：
        1. 第一步：修复所有边界违规
        2. 第二步：修复所有碰撞违规
        3. 如果修复碰撞引入新的边界违规，重复步骤1-2
        4. 迭代直到收敛或达到最大循环次数
        """
        current_layout = json.loads(json.dumps(initial_layout))
        current_violation_count = initial_violation_count
        max_fix_rounds = 5  # 最多5轮修复循环
        
        logger.info("=" * 60)
        logger.info("开始分阶段渐进式自动修复")
        logger.info("=" * 60)
        
        # === 第0步：批量修复所有高度错误（一次性完成）===
        logger.info("\n【第0步：批量修复高度错误】")
        height_fixes = initial_evaluation.get('improvement_suggestions', {}).get('critical_fixes', [])
        height_fixes = [f for f in height_fixes if f.get('type') == 'height_error_batch']
        
        if height_fixes:
            height_fix_count = 0
            for fix in height_fixes:
                objects_to_fix = fix.get('objects', [])
                
                for obj_id in objects_to_fix:
                    obj = next((o for o in current_layout['objects'] if o['id'] == obj_id), None)
                    if obj and 'position' in obj:
                        old_z = obj['position'].get('z')
                        
                        # 统一高度修复为0.8m（分层在最后阶段进行）
                        expected_z = 0.8
                        obj['position']['z'] = expected_z
                        height_fix_count += 1
                        
                        logger.info(f"  ✓ 修复 {obj_id} 高度: {old_z} → {expected_z}m")
            
            if height_fix_count > 0:
                logger.info(f"\n  ✓ 批量修复了 {height_fix_count} 个高度错误")
                # 重新评估
                self._write_layout(current_layout)
                eval_result = self.evaluation_runner.run_full_pipeline(
                    self.layout_path,
                    self.protocol_path,
                    iteration_dir / "fix_height_batch",
                    skip_semantic=True
                )
                current_violation_count = EvaluationSummarizer(eval_result).violation_count()
                logger.info(f"  高度修复后违规数: {current_violation_count}")
        
        for fix_round in range(1, max_fix_rounds + 1):
            logger.info(f"\n【修复循环 {fix_round}/{max_fix_rounds}】当前违规数: {current_violation_count}")
            
            round_improved = False
            
            # === 阶段1: 修复边界违规 ===
            logger.info("\n  阶段1: 修复边界违规")
            boundary_layout, boundary_improved = self._fix_violations_by_type(
                current_layout,
                current_violation_count,
                'boundary',
                iteration_dir / f"fix_round_{fix_round}_boundary",
                optimize_mode=optimize_mode
            )
            
            if boundary_improved:
                current_layout = boundary_layout
                # 重新评估以获取最新违规数
                self._write_layout(current_layout)
                eval_result = self.evaluation_runner.run_full_pipeline(
                    self.layout_path,
                    self.protocol_path,
                    iteration_dir / f"fix_round_{fix_round}_boundary_eval",
                    skip_semantic=True
                )
                current_violation_count = EvaluationSummarizer(eval_result).violation_count()
                logger.info(f"    ✓ 边界修复有效，当前违规数: {current_violation_count}")
                round_improved = True
            else:
                logger.info(f"    = 边界修复无效或无需修复")
            
            # === 阶段2: 修复碰撞违规 ===
            logger.info("\n  阶段2: 修复碰撞违规")
            collision_layout, collision_improved = self._fix_violations_by_type(
                current_layout,
                current_violation_count,
                'collision',
                iteration_dir / f"fix_round_{fix_round}_collision",
                optimize_mode=optimize_mode
            )
            
            if collision_improved:
                current_layout = collision_layout
                # 重新评估以获取最新违规数
                self._write_layout(current_layout)
                eval_result = self.evaluation_runner.run_full_pipeline(
                    self.layout_path,
                    self.protocol_path,
                    iteration_dir / f"fix_round_{fix_round}_collision_eval",
                    skip_semantic=True
                )
                new_violation_count = EvaluationSummarizer(eval_result).violation_count()
                logger.info(f"    ✓ 碰撞修复有效，违规: {current_violation_count} → {new_violation_count}")
                
                # 检查是否引入新的边界违规
                boundary_violations = self._count_violations_by_type(eval_result, 'boundary')
                if boundary_violations > 0:
                    logger.info(f"    ⚠ 修复碰撞引入了 {boundary_violations} 个新边界违规，将在下轮继续修复")
                
                current_violation_count = new_violation_count
                round_improved = True
            else:
                logger.info(f"    = 碰撞修复无效或无需修复")
            
            # 检查是否收敛
            if not round_improved:
                logger.info(f"\n✓ 修复收敛，共完成 {fix_round} 轮，最终违规数: {current_violation_count}")
                break
            
            # 如果违规数已经很少，提前结束
            if current_violation_count <= 2:
                logger.info(f"\n✓ 违规数已降至 {current_violation_count}，提前结束修复")
                break
        
        improvement = initial_violation_count - current_violation_count
        if improvement > 0:
            logger.info(f"\n{'='*60}")
            logger.info(f"自动修复总结: 违规 {initial_violation_count} → {current_violation_count} (减少 {improvement} 个)")
            logger.info(f"{'='*60}")
        
        # 构建修复报告
        fix_report = {
            'initial_violation_count': initial_violation_count,
            'final_violation_count': current_violation_count,
            'improvement': improvement,
            'fix_rounds': fix_round,
            'boundary_fixes_applied': 0,
            'collision_fixes_applied': 0,
            'boundary_fixes_failed': 0,
            'collision_fixes_failed': 0,
            'remaining_collisions': []
        }
        
        # 重新评估以获取剩余碰撞信息
        self._write_layout(current_layout)
        final_evaluation = self.evaluation_runner.run_full_pipeline(
            self.layout_path,
            self.protocol_path,
            iteration_dir / "final_eval",
            skip_semantic=True
        )
        
        # 提取剩余碰撞
        physical_constraints = final_evaluation.get('physical_evaluation', {}).get('physical_constraints', {})
        collision_violations = physical_constraints.get('collision', {}).get('violations', [])
        room_collision_violations = physical_constraints.get('room_assets', {}).get('violations', [])
        
        # 过滤出碰撞违规
        for v in room_collision_violations:
            if v.get('constraint') == 'room_collision_check':
                collision_violations.append(v)
        
        fix_report['remaining_collisions'] = [
            {
                'objects': v.get('objects', []),
                'work_surface': v.get('work_surface', 'unknown'),
                'overlap_area': v.get('overlap_area', 0),
                'positions': v.get('positions', {})
            }
            for v in collision_violations
        ]
        
        return current_layout, fix_report
    
    def _fix_violations_by_type(
        self,
        layout: Dict,
        current_violation_count: int,
        fix_type: str,  # 'boundary' 或 'collision'
        work_dir: Path,
        optimize_mode: str = "desktop"
    ) -> tuple[Dict, bool]:
        """
        修复指定类型的违规
        
        Returns:
            (修复后的布局, 是否改善)
        """
        work_dir.mkdir(parents=True, exist_ok=True)
        
        # 先评估以获取违规信息
        self._write_layout(layout)
        evaluation = self.evaluation_runner.run_full_pipeline(
            self.layout_path,
            self.protocol_path,
            work_dir / "evaluation",
            skip_semantic=True
        )
        
        # 根据优化阶段获取修复前的相关违规数
        if optimize_mode == "room":
            # Phase1_Room：只统计房间资产违规
            physical_constraints = evaluation.get('physical_evaluation', {}).get('physical_constraints', {})
            room_assets = physical_constraints.get('room_assets', {})
            current_relevant_violations = len(room_assets.get('violations', []))
        else:
            # Phase2_Desktop或其他：使用总违规数
            current_relevant_violations = current_violation_count
        
        # 提取指定类型的修复指令
        auto_fixes = evaluation.get('improvement_suggestions', {}).get('auto_fixes', [])
        if fix_type == 'boundary':
            type_fixes = [f for f in auto_fixes if f.get('type') == 'boundary_fix']
        else:  # collision
            type_fixes = [f for f in auto_fixes if f.get('type') == 'collision_fix']
        
        if not type_fixes:
            return layout, False
        
        logger.info(f"    找到 {len(type_fixes)} 个{fix_type}修复指令")
        
        # 合并修复指令（避免冲突）
        merged_fixes = self._merge_auto_fixes(type_fixes)
        if len(merged_fixes) < len(type_fixes):
            logger.info(f"    合并后剩余 {len(merged_fixes)} 个修复指令")
        
        # 应用修复
        temp_layout = json.loads(json.dumps(layout))
        fixes_applied = self._apply_auto_fixes(temp_layout, merged_fixes)
        
        if fixes_applied == 0:
            return layout, False
        
        # 验证修复效果
        self._write_layout(temp_layout)
        new_evaluation = self.evaluation_runner.run_full_pipeline(
            self.layout_path,
            self.protocol_path,
            work_dir / "check",
            skip_semantic=True
        )
        
        # 根据优化阶段统计违规数
        if optimize_mode == "room":
            # Phase1_Room：只统计房间资产违规（不包含桌面违规）
            physical_constraints = new_evaluation.get('physical_evaluation', {}).get('physical_constraints', {})
            room_assets = physical_constraints.get('room_assets', {})
            new_relevant_violations = len(room_assets.get('violations', []))
            
            logger.info(f"    房间资产违规: {current_relevant_violations} → {new_relevant_violations}")
            
            if new_relevant_violations < current_relevant_violations:
                return temp_layout, True
            else:
                # 回滚
                self._write_layout(layout)
                logger.info(f"    修复无效（房间资产违规未减少），回滚")
                return layout, False
        else:
            # Phase2_Desktop或其他：使用总违规数
            new_violation_count = EvaluationSummarizer(new_evaluation).violation_count()
            
            if new_violation_count < current_violation_count:
                return temp_layout, True
            else:
                # 回滚
                self._write_layout(layout)
                logger.info(f"    修复无效（总违规数未减少），回滚")
                return layout, False
    
    def _count_violations_by_type(self, evaluation: Dict, violation_type: str) -> int:
        """统计指定类型的违规数"""
        physical = evaluation.get('physical_evaluation', {})
        violations = physical.get('violations', [])
        physical_constraints = physical.get('physical_constraints', {})
        
        all_violations = list(violations)
        all_violations.extend(physical_constraints.get('boundary', {}).get('violations', []))
        all_violations.extend(physical_constraints.get('collision', {}).get('violations', []))
        all_violations.extend(physical_constraints.get('room_assets', {}).get('violations', []))
        
        count = sum(1 for v in all_violations if violation_type in v.get('constraint', '').lower())
        return count
    
    def _apply_auto_fixes(self, layout: Dict, auto_fixes: List[Dict]) -> int:
        """
        应用自动修复指令
        
        Args:
            layout: 布局JSON
            auto_fixes: 自动修复指令列表
        
        Returns:
            应用的修复数量
        """
        applied_count = 0
        applied_objects = set()  # 记录已应用修复的对象(对象ID+位置)，避免重复应用
        
        for fix in auto_fixes:
            fix_type = fix.get('type')
            
            if fix_type == 'boundary_fix':
                obj_id = fix['object_id']
                action = fix['action']
                old_pos_from_fix = fix.get('violation', {}).get('current_position')  # 从违规记录中获取原始位置
                
                # 查找并更新对象（优先精确匹配ID，如果ID相同则通过位置匹配）
                best_match = None
                min_distance = float('inf')
                
                for obj in layout.get('objects', []):
                    if obj['id'] == obj_id:
                        obj_pos = obj['position']
                        # 如果提供了原始位置，通过位置匹配来区分同名对象
                        if old_pos_from_fix:
                            distance = abs(obj_pos.get('x', 0) - old_pos_from_fix.get('x', 0)) + \
                                      abs(obj_pos.get('y', 0) - old_pos_from_fix.get('y', 0))
                            if distance < min_distance and distance < 0.1:  # 10cm容差
                                min_distance = distance
                                best_match = obj
                        else:
                            # 如果没有原始位置信息，使用第一个匹配的对象
                            if best_match is None:
                                best_match = obj
                
                if best_match:
                    # 检查是否已经应用过修复（避免重复应用）
                    obj_key = (obj_id, best_match['position']['x'], best_match['position']['y'])
                    if obj_key in applied_objects:
                        logger.warning(f"  ⚠ 跳过重复修复: {obj_id} 在位置 ({best_match['position']['x']:.3f}, {best_match['position']['y']:.3f})")
                        continue
                    
                    # 检查是否是工作表面，需要同步桌面物体
                    is_work_surface = obj_id in ['ExperimentalPlatform', 'ValidationPlatform', 'FumeHood', 
                                                  'LabBench', 'Workbench', 'ReagentCabinet', 'Cabinet', 'Shelf']
                    
                    # 记录旧位置
                    old_pos = best_match['position'].copy()
                    
                    axis = action['axis']
                    old_val = best_match['position'][axis]
                    new_val = action['new_value']
                    
                    best_match['position'][axis] = new_val
                    
                    # 如果是工作表面，同步桌面物体
                    if is_work_surface:
                        delta_x = best_match['position']['x'] - old_pos['x']
                        delta_y = best_match['position']['y'] - old_pos['y']
                        if abs(delta_x) > 1e-6 or abs(delta_y) > 1e-6:
                            # 同步该工作表面上的所有桌面物体
                            self._sync_desktop_objects_for_surface(layout, obj_id, delta_x, delta_y)
                            logger.info(f"    同步桌面物体: {obj_id} 移动 ({delta_x:.3f}, {delta_y:.3f})")
                    
                    applied_objects.add((obj_id, best_match['position']['x'], best_match['position']['y']))
                    
                    logger.info(f"  - {obj_id}.position.{axis}: {old_val:.3f} → {new_val:.3f} ({fix['description']})")
                    applied_count += 1
            
            elif fix_type == 'collision_fix':
                move_obj = fix['move_object']
                action = fix['action']
                old_pos_from_fix = action.get('old_position')  # 从修复指令中获取原始位置
                new_pos = action['new_position']
                
                # 查找并更新对象（优先精确匹配ID，如果ID相同则通过位置匹配）
                best_match = None
                min_distance = float('inf')
                
                for obj in layout.get('objects', []):
                    if obj['id'] == move_obj:
                        obj_pos = obj['position']
                        # 如果提供了原始位置，通过位置匹配来区分同名对象
                        if old_pos_from_fix:
                            distance = abs(obj_pos.get('x', 0) - old_pos_from_fix.get('x', 0)) + \
                                      abs(obj_pos.get('y', 0) - old_pos_from_fix.get('y', 0))
                            if distance < min_distance and distance < 0.1:  # 10cm容差
                                min_distance = distance
                                best_match = obj
                        else:
                            # 如果没有原始位置信息，使用第一个匹配的对象
                            if best_match is None:
                                best_match = obj
                
                if best_match:
                    # 检查是否已经应用过修复（避免重复应用）
                    obj_key = (move_obj, best_match['position']['x'], best_match['position']['y'])
                    if obj_key in applied_objects:
                        logger.warning(f"  ⚠ 跳过重复修复: {move_obj} 在位置 ({best_match['position']['x']:.3f}, {best_match['position']['y']:.3f})")
                        continue
                    
                    old_pos = best_match['position'].copy()
                    best_match['position']['x'] = new_pos['x']
                    best_match['position']['y'] = new_pos['y']
                    applied_objects.add((move_obj, new_pos['x'], new_pos['y']))
                    
                    logger.info(f"  - {move_obj}: ({old_pos['x']:.3f}, {old_pos['y']:.3f}) → ({new_pos['x']:.3f}, {new_pos['y']:.3f})")
                    logger.info(f"    原因: {fix['description']}")
                    applied_count += 1
        
        return applied_count
    
    def _sync_desktop_objects_for_surface(self, layout: Dict, surface_id: str, delta_x: float, delta_y: float) -> None:
        """
        同步移动工作表面上的所有桌面物体
        
        Args:
            layout: 布局JSON
            surface_id: 工作表面ID（如 "ReagentCabinet"）
            delta_x: X方向移动距离
            delta_y: Y方向移动距离
        """
        # 规范化工作表面ID（去除可能的#后缀）
        base_surface_id = surface_id.split("#")[0]
        
        # 建立映射表：PascalCase -> snake_case（与LayoutEditor保持一致）
        surface_name_mapping = {
            "ReagentCabinet": "reagent_cabinet",
            "ExperimentalPlatform": "experimental_platform",
            "ValidationPlatform": "validation_platform",
            "FumeHood": "FumeHood",
            "LabBench": "lab_bench",
            "Workbench": "workbench",
            "Cabinet": "cabinet",
            "Shelf": "shelf",
        }
        
        # 获取规范化的工作表面名称
        normalized_surface_id = surface_name_mapping.get(base_surface_id, base_surface_id.lower())
        
        # 查找所有桌面物体
        objects = layout.get("objects", [])
        synced_count = 0
        for obj in objects:
            initial_location = obj.get("initial_location", "")
            if not initial_location or initial_location == "floor":
                continue
            
            # 规范化initial_location（去除可能的#后缀）
            base_location = initial_location.split("#")[0]
            normalized_location = surface_name_mapping.get(base_location, base_location.lower())
            
            # 如果桌面物体属于该工作表面，同步移动
            if normalized_location == normalized_surface_id:
                obj_pos = obj.get("position", {})
                if "x" in obj_pos:
                    obj_pos["x"] = obj_pos["x"] + delta_x
                if "y" in obj_pos:
                    obj_pos["y"] = obj_pos["y"] + delta_y
                synced_count += 1
                logger.debug(f"      同步移动: {obj.get('id')} ({delta_x:.3f}, {delta_y:.3f})")
        
        if synced_count > 0:
            logger.info(f"    已同步 {synced_count} 个桌面物体")
    
    def _sync_desktop_objects_for_surface(self, layout: Dict, surface_id: str, delta_x: float, delta_y: float) -> None:
        """
        同步移动工作表面上的所有桌面物体
        
        Args:
            layout: 布局JSON
            surface_id: 工作表面ID（如 "ReagentCabinet"）
            delta_x: X方向移动距离
            delta_y: Y方向移动距离
        """
        # 规范化工作表面ID（去除可能的#后缀）
        base_surface_id = surface_id.split("#")[0]
        
        # 查找所有桌面物体
        objects = layout.get("objects", [])
        for obj in objects:
            initial_location = obj.get("initial_location", "")
            if not initial_location or initial_location == "floor":
                continue
            
            # 规范化initial_location（去除可能的#后缀）
            base_location = initial_location.split("#")[0]
            
            # 如果桌面物体属于该工作表面，同步移动
            if base_location == base_surface_id:
                obj_pos = obj.get("position", {})
                if "x" in obj_pos:
                    obj_pos["x"] = obj_pos["x"] + delta_x
                if "y" in obj_pos:
                    obj_pos["y"] = obj_pos["y"] + delta_y
                logger.debug(f"      同步移动: {obj.get('id')} ({delta_x:.3f}, {delta_y:.3f})")

    def _generate_summary(self) -> Dict:
        """生成优化摘要"""
        logger.info("优化流程结束，已执行 %d 轮", len(self.iterations))

        # 恢复最佳布局
        self._write_layout(self.best_layout)
        return {
            "best_score": self.best_score,
            "best_violation_count": self.best_violation_count,
            "iterations": [
                {
                    "iteration": rec.iteration,
                    "score": rec.score,
                    "violation_count": rec.violation_count,
                    "adjustments": rec.adjustments,
                    "evaluation_report": str(rec.evaluation_report_path)
                    if rec.evaluation_report_path
                    else None,
                }
                for rec in self.iterations
            ],
        }


