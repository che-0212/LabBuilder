#!/usr/bin/env python3
"""
批量并行生成实验协议

使用方法:
    python batch_generate_protocols_parallel.py [--workers N] [--ragflow-api-key KEY]
"""

import json
import os
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Tuple
import traceback

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from labforge import ProtocolPlanner
from utils.llm_config import LLMConfig


def load_experiment_ids_from_file(file_path: str) -> List[str]:
    """从文件中加载实验ID列表"""
    exp_ids = []
    exp_ids_path = project_root / file_path
    if not exp_ids_path.exists():
        return []
    
    with open(exp_ids_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and line.startswith('exp_'):
                exp_ids.append(line)
    return exp_ids


# 从文件加载实验ID
EXPERIMENT_IDS_FILE = os.environ.get('EXPERIMENT_IDS_FILE', 'DATA/exp_ids_to_generate.txt')
EXPERIMENT_IDS = load_experiment_ids_from_file(EXPERIMENT_IDS_FILE)


def load_experiments(experiments_file: str) -> List[Dict]:
    """加载实验列表"""
    with open(experiments_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('experiments', [])


def generate_single_protocol(args: Tuple[int, Dict, str, str, str]) -> Dict:
    """
    生成单个实验的 protocol
    
    Args:
        args: (experiment_id, experiment_data, output_dir, ragflow_api_key, ragflow_base_url)
    
    Returns:
        结果字典，包含状态和信息
    """
    exp_id, experiment, output_dir, ragflow_api_key, ragflow_base_url = args
    
    result = {
        'experiment_id': exp_id,
        'experiment_name': experiment.get('name', f'Experiment_{exp_id}'),
        'status': 'pending',
        'message': '',
        'protocol_file': None,
        'error': None
    }
    
    try:
        print(f"[{exp_id}] 开始生成: {result['experiment_name']}")
        
        # 获取实验描述
        description = experiment.get('description', '')
        if not description:
            result['status'] = 'skipped'
            result['message'] = 'No description available'
            print(f"[{exp_id}] ⚠ 跳过: 无实验描述")
            return result
        
        # 初始化 planner
        llm_config = LLMConfig()
        
        planner = ProtocolPlanner(
            asset_library_path='assets_annotated.json',
            llm_config=llm_config,
            asset_captions_path='assets_annotated_captions.json',
            ragflow_api_key=ragflow_api_key,
            ragflow_base_url=ragflow_base_url,
            enable_rag=True
        )
        
        # 生成 protocol
        protocol, filepath = planner.plan_and_save(
            experiment_description=description,
            output_dir=output_dir,
            verbose=False,  # 关闭详细输出以减少日志混乱
            strict_validation=True,
            max_retries=10,  # 增加重试次数以让LLM找到替代品
            max_tokens=32000  # 增加 max_tokens 以避免响应被截断
        )
        
        # 在protocol文件中添加experiment_id字段，并放在最前面
        with open(filepath, 'r', encoding='utf-8') as f:
            protocol_data = json.load(f)
        
        # 重新组织字典，将experiment_id放在最前面
        reordered_data = {'experiment_id': exp_id}
        for key, value in protocol_data.items():
            reordered_data[key] = value
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(reordered_data, f, indent=2, ensure_ascii=False)
        
        result['status'] = 'success'
        result['protocol_file'] = filepath
        result['message'] = f'Successfully generated protocol'
        print(f"[{exp_id}] ✓ 成功生成: {os.path.basename(filepath)}")
        
    except Exception as e:
        result['status'] = 'failed'
        result['error'] = str(e)
        result['message'] = f'Failed: {str(e)}'
        print(f"[{exp_id}] ✗ 失败: {str(e)}")
        # 打印详细错误信息到文件
        error_log = os.path.join(output_dir, f'error_exp_{exp_id}.log')
        with open(error_log, 'w', encoding='utf-8') as f:
            f.write(f"Experiment ID: {exp_id}\n")
            f.write(f"Experiment Name: {result['experiment_name']}\n")
            f.write(f"Error: {str(e)}\n\n")
            f.write(traceback.format_exc())
        result['error_log'] = error_log
    
    return result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='批量并行生成实验协议')
    parser.add_argument(
        '--workers',
        type=int,
        default=30,
        help='并行处理的数量 (default: 30)'
    )
    parser.add_argument(
        '--experiments-file',
        type=str,
        default='DATA/experiments.json',
        help='实验列表文件 (default: DATA/experiments.json)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='DATA/Protocols_30',
        help='输出目录 (default: DATA/Protocols_30)'
    )
    parser.add_argument(
        '--experiment-ids-file',
        type=str,
        default='DATA/exp_ids_to_generate.txt',
        help='实验ID列表文件 (default: DATA/exp_ids_to_generate.txt)'
    )
    parser.add_argument(
        '--ragflow-api-key',
        type=str,
        default=None,
        help='RAGflow API key (optional, set via --ragflow-api-key or RAGFLOW_API_KEY env var)'
    )
    parser.add_argument(
        '--ragflow-base-url',
        type=str,
        default=None,
        help='RAGflow base URL (optional, set via --ragflow-base-url or RAGFLOW_BASE_URL env var)'
    )
    
    args = parser.parse_args()
    
    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 加载实验ID列表
    experiment_ids = load_experiment_ids_from_file(args.experiment_ids_file)
    if not experiment_ids:
        print(f"❌ 错误: 从 {args.experiment_ids_file} 中未找到实验ID")
        return 1
    print(f"✓ 已加载 {len(experiment_ids)} 个实验ID")
    
    # 加载实验列表
    print(f"加载实验列表: {args.experiments_file}")
    all_experiments = load_experiments(args.experiments_file)
    print(f"✓ 已加载 {len(all_experiments)} 个实验")
    
    # 创建实验ID到实验数据的映射
    experiment_dict = {exp.get('id'): exp for exp in all_experiments if exp.get('id')}
    
    # 准备任务列表（只生成指定的实验ID）
    tasks = []
    missing_ids = []
    for exp_id in experiment_ids:
        if exp_id in experiment_dict:
            experiment = experiment_dict[exp_id]
            tasks.append((exp_id, experiment, args.output_dir, args.ragflow_api_key, args.ragflow_base_url))
        else:
            missing_ids.append(exp_id)
            print(f"⚠ 警告: 实验ID {exp_id} 在实验列表中未找到，跳过")
    
    if missing_ids:
        print(f"\n⚠ 警告: {len(missing_ids)} 个实验ID未找到: {missing_ids}")
    
    print(f"\n开始批量生成 {len(tasks)} 个实验的 protocol")
    print(f"并行数量: {args.workers}")
    print(f"输出目录: {args.output_dir}")
    print("=" * 80)
    
    # 并行处理
    start_time = datetime.now()
    results = []
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # 提交所有任务
        future_to_id = {executor.submit(generate_single_protocol, task): task[0] for task in tasks}
        
        # 收集结果
        completed = 0
        for future in as_completed(future_to_id):
            exp_id = future_to_id[future]
            try:
                result = future.result()
                results.append(result)
                completed += 1
                print(f"进度: {completed}/{len(tasks)} 完成")
            except Exception as e:
                print(f"[{exp_id}] ✗ 处理异常: {str(e)}")
                results.append({
                    'experiment_id': exp_id,
                    'status': 'error',
                    'error': str(e)
                })
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # 统计结果
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = sum(1 for r in results if r['status'] == 'failed')
    skipped_count = sum(1 for r in results if r['status'] == 'skipped')
    error_count = sum(1 for r in results if r['status'] == 'error')
    
    # 保存结果摘要
    summary = {
        'timestamp': datetime.now().isoformat(),
        'total_experiments': len(tasks),
        'success': success_count,
        'failed': failed_count,
        'skipped': skipped_count,
        'errors': error_count,
        'duration_seconds': duration,
        'workers': args.workers,
        'results': results
    }
    
    summary_file = os.path.join(args.output_dir, f'batch_summary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    # 打印总结
    print("\n" + "=" * 80)
    print("批量生成完成！")
    print("=" * 80)
    print(f"总计: {len(tasks)} 个实验")
    print(f"✓ 成功: {success_count}")
    print(f"✗ 失败: {failed_count}")
    print(f"⚠ 跳过: {skipped_count}")
    print(f"✗ 错误: {error_count}")
    print(f"耗时: {duration:.2f} 秒 ({duration/60:.2f} 分钟)")
    print(f"平均: {duration/len(tasks):.2f} 秒/实验")
    print(f"\n结果摘要: {summary_file}")
    print(f"输出目录: {args.output_dir}")
    
    # 列出失败的实验
    if failed_count > 0:
        print("\n失败的实验:")
        for r in results:
            if r['status'] == 'failed':
                print(f"  - [{r['experiment_id']}] {r['experiment_name']}: {r['message']}")
    
    return 0 if failed_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

