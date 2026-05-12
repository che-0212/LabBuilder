"""
优化器配置
"""

from pathlib import Path

OPTIMIZER_CONFIG = {
    "max_iterations": 5,
    "score_improvement_threshold": 1.0,  # 分数提升小于该值视为收敛
    "violation_reduction_threshold": 1,  # 违规减少小于该值视为收敛
    "no_improvement_rounds": 2,          # 连续几轮无改进则停止
    "llm_model": "claude-sonnet-4-5-20250929",
    "llm_temperature": 0.3,              # 提高温度，让LLM更快速决策（0.2 → 0.7）
    "llm_max_tokens": 40000,              # 降低到合理值，加快响应（60000 → 8000）
    "skip_semantic_evaluation": False,   # 是否跳过语义评估（只优化物理70分）
}

# 使用相对路径，基于当前工作目录
_PROJECT_ROOT = Path(__file__).parent.parent  # Table/Lablayout目录
_TABLE_ROOT = _PROJECT_ROOT.parent  # Table目录

SCRIPT_PATHS = {
    "usd_generator": _TABLE_ROOT / "usd.sh",
    "renderer": _PROJECT_ROOT / "rendering_tools" / "render_final_5_views.sh",
    "evaluator": _PROJECT_ROOT / "evaluate_layout.sh",
    "images_dir": _PROJECT_ROOT / "rendering_tools" / "final_5_views",
}


