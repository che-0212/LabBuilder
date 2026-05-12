"""
优化器命令行入口
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from labgen.optimizer.optimizer_engine import LLMOptimizerEngine
from labgen.optimizer.config import OPTIMIZER_CONFIG


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM 指导的实验室布局优化器",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--layout", required=True, help="输入布局 JSON 路径")
    parser.add_argument("--protocol", required=True, help="实验协议 JSON 路径")
    parser.add_argument("--asset-library", default="assets_annotated.json", help="资产库 JSON 路径")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="优化工作目录（默认: OUTPUT/optimizer/<timestamp>）",
    )
    parser.add_argument(
        "--output-layout",
        default=None,
        help="优化后的布局输出路径（默认覆盖原布局）",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=OPTIMIZER_CONFIG["max_iterations"],
        help="最大优化迭代次数",
    )
    parser.add_argument(
        "--skip-semantic",
        action="store_true",
        help="跳过语义评估（快速模式，只优化物理70分，不生成USD和渲染）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-5-20250929",
        help="LLM 模型名称",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="LLM 生成温度",
    )
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("optimizer")

    layout_path = Path(args.layout)
    protocol_path = Path(args.protocol)
    asset_library_path = Path(args.asset_library)

    if not layout_path.exists():
        logger.error("布局文件不存在: %s", layout_path)
        return 1
    if not protocol_path.exists():
        logger.error("协议文件不存在: %s", protocol_path)
        return 1
    if not asset_library_path.exists():
        logger.error("资产库文件不存在: %s", asset_library_path)
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = (
            Path("OUTPUT") / "optimizer_runs" / f"{layout_path.stem}_{timestamp}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    OPTIMIZER_CONFIG["max_iterations"] = args.max_iterations
    OPTIMIZER_CONFIG["skip_semantic_evaluation"] = args.skip_semantic
    OPTIMIZER_CONFIG["llm_model"] = args.model
    OPTIMIZER_CONFIG["llm_temperature"] = args.temperature

    logger.info("工作目录: %s", output_dir.resolve())
    logger.info("最大迭代次数: %d", args.max_iterations)
    logger.info("使用模型: %s", args.model)
    logger.info("Temperature: %.2f", args.temperature)
    if args.skip_semantic:
        logger.info("⚡ 快速优化模式：跳过语义评估（只优化物理70分）")

    engine = LLMOptimizerEngine(
        layout_path=layout_path,
        protocol_path=protocol_path,
        working_dir=output_dir,
        asset_library_path=asset_library_path,
    )

    try:
        summary = engine.optimize()
    except Exception as exc:
        logger.exception("优化失败: %s", exc)
        return 1

    best_layout = Path(args.output_layout) if args.output_layout else layout_path
    with best_layout.open("w", encoding="utf-8") as f:
        json.dump(engine.best_layout, f, indent=2, ensure_ascii=False)
    logger.info("优化后的布局已保存到: %s", best_layout.resolve())

    summary_path = output_dir / "optimization_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info("优化摘要已保存到: %s", summary_path.resolve())

    logger.info(
        "最佳得分: %.2f, 剩余违规: %d",
        summary["best_score"],
        summary["best_violation_count"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())


