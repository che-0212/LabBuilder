"""
主评估流程
整合物理评估和语义评估，生成完整报告
"""

import os
import argparse
from pathlib import Path
from labtouchstone.evaluator.physical_evaluator import PhysicalEvaluator
from labtouchstone.evaluator.semantic_evaluator import SemanticEvaluator
from labtouchstone.evaluator.report_generator import ReportGenerator
from labtouchstone.evaluator.utils.asset_loader import AssetLoader
from labtouchstone.evaluator.utils.file_utils import load_json, get_output_paths


def evaluate_layout(layout_path: str, protocol_path: str, asset_db_path: str,
                   images_dir: str, output_dir: str, skip_semantic: bool = False):
    """
    评估单个布局
    
    Args:
        layout_path: 布局JSON文件路径
        protocol_path: 协议JSON文件路径
        asset_db_path: Asset.json路径
        images_dir: 渲染图片目录
        output_dir: 输出目录
        skip_semantic: 是否跳过语义评估
    """
    print("=" * 60)
    print("开始布局评估")
    print("=" * 60)
    
    # 1. 加载数据
    print("\n[1/5] 加载数据...")
    layout = load_json(layout_path)
    protocol = load_json(protocol_path)
    experiment_name = protocol.get('experiment_name', 'Unknown_Experiment')
    
    print(f"实验名称：{experiment_name}")
    print(f"布局文件：{layout_path}")
    print(f"协议文件：{protocol_path}")
    
    # 2. 物理评估
    print("\n[2/5] 物理评估（70分）...")
    physical_evaluator = PhysicalEvaluator(asset_db_path)
    physical_result = physical_evaluator.evaluate(layout, protocol)
    
    print(f"物理评估得分：{physical_result['total_score']:.1f}/70")
    print(f"  - 物理约束：{physical_result['physical_constraints']['score']:.1f}/35")
    print(f"  - 化学约束：{physical_result['chemical_constraints']['score']:.1f}/35")
    print(f"  - 违规数量：{len(physical_result['violations'])}")
    
    # 检查是否严重不合格
    if physical_result['total_score'] < 20:
        print("\n⚠️  警告：物理评估得分过低（<20分），布局存在严重问题")
        print("建议修正后再进行语义评估")
        # 仍然继续评估，但给出警告
    
    # 3. 语义评估
    if skip_semantic:
        print("\n[3/5] 语义评估（30分）... ⚠️ 跳过（快速优化模式）")
        # 创建空的语义评估结果
        semantic_result = {
            'total_score': 0,
            'max_score': 30,
            'average_score': 0,
            'questions': [],
            'low_score_items': [],
            'summary': '跳过语义评估（快速优化模式）'
        }
    else:
        print("\n[3/5] 语义评估（30分）...")
        semantic_evaluator = SemanticEvaluator()
        # 传递物理评估结果用于交叉验证
        semantic_result = semantic_evaluator.evaluate(protocol, images_dir, experiment_name, physical_result)
        
        print(f"语义评估得分：{semantic_result['total_score']:.1f}/30")
        print(f"  - 平均分：{semantic_result['average_score']:.1f}/6")
        print(f"  - 低分项：{len(semantic_result['low_score_items'])}")
    
    # 4. 生成报告
    print("\n[4/5] 生成评估报告...")
    # 创建资产加载器（用于获取化学属性，生成隐式安全提示）
    asset_loader = AssetLoader(asset_db_path)
    report_generator = ReportGenerator(asset_loader)
    report = report_generator.generate_report(
        physical_result,
        semantic_result,
        layout_path,
        protocol_path,
        experiment_name
    )
    
    # 5. 保存报告
    print("\n[5/5] 保存报告...")
    output_paths = get_output_paths(output_dir, experiment_name)
    
    # 保存JSON报告
    report_generator.save_report(report, output_paths['json_report'])
    
    # 保存HTML报告
    report_generator.generate_html_report(report, output_paths['html_report'])
    
    # 打印总结
    print("\n" + "=" * 60)
    print("评估完成！")
    print("=" * 60)
    print(f"总分：{report['scores']['total']}/100 （等级：{report['scores']['grade']}）")
    print(f"状态：{'✅ 通过' if report['scores']['passed'] else '❌ 不通过'}")
    print(f"关键问题数量：{len(report['critical_issues'])}")
    print(f"\n报告已保存到：{output_dir}")
    print("=" * 60)
    
    return report


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='评估实验室布局')
    parser.add_argument('--layout', required=True, help='布局JSON文件路径')
    parser.add_argument('--protocol', required=True, help='协议JSON文件路径')
    # 使用相对路径，基于当前工作目录
    _project_root = Path(__file__).parent.parent  # Table/Lablayout目录
    _default_asset_db = _project_root / 'assets_annotated.json'
    parser.add_argument('--asset-db', default=str(_default_asset_db),
                       help='assets_annotated.json路径')
    _default_images_dir = _project_root / 'rendering_tools' / 'final_5_views'
    parser.add_argument('--images-dir', default=str(_default_images_dir),
                       help='渲染图片基础目录')
    parser.add_argument('--output', required=True, help='输出目录')
    parser.add_argument('--skip-semantic', action='store_true', help='跳过语义评估（快速模式，只评估物理70分）')
    
    args = parser.parse_args()
    
    evaluate_layout(
        args.layout,
        args.protocol,
        args.asset_db,
        args.images_dir,
        args.output,
        skip_semantic=args.skip_semantic
    )


if __name__ == '__main__':
    main()

