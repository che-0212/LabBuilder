#!/usr/bin/env python3
"""
批量并行生成初始布局

使用方法:
    python batch_generate_layouts_parallel.py [--workers N] [--input-dir DIR] [--output-dir DIR]
"""

import json
import os
import sys
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Tuple
import traceback

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from labgen.layout_generator.layout_engine_v3 import LLMLayoutEngineV3


def find_protocol_files(input_dir: str) -> List[str]:
    """
    查找输入目录下的所有 protocol 文件
    
    Args:
        input_dir: 输入目录路径
    
    Returns:
        protocol 文件路径列表
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"⚠ 警告: 输入目录不存在: {input_dir}")
        return []
    
    # 查找所有 protocol_*.json 文件，排除 batch_summary 和 error 文件
    protocol_files = []
    for file in input_path.glob("protocol_*.json"):
        if "batch_summary" not in file.name and "error" not in file.name:
            protocol_files.append(str(file))
    
    return sorted(protocol_files)


def generate_single_layout_no_retry(protocol_file: str, output_dir: str, asset_library_path: str, llm_config: Dict, attempt: int = 1) -> Dict:
    """
    单次尝试生成布局
    
    Args:
        protocol_file: protocol 文件路径
        output_dir: 输出目录
        asset_library_path: 资产库路径
        llm_config: LLM 配置
        attempt: 当前尝试次数
    
    Returns:
        结果字典
    """
    result = {
        'protocol_file': protocol_file,
        'status': 'pending',
        'message': '',
        'layout_file': None,
        'error': None,
        'attempt': attempt
    }
    
    try:
        # 加载 protocol
        with open(protocol_file, 'r', encoding='utf-8') as f:
            protocol = json.load(f)
        
        experiment_name = protocol.get('experiment_name', Path(protocol_file).stem)
        result['experiment_name'] = experiment_name
        
        print(f"[{Path(protocol_file).name}] 开始生成: {experiment_name}")
        
        # 初始化布局引擎
        engine = LLMLayoutEngineV3(
            asset_library_path=asset_library_path,
            llm_config=llm_config
        )
        
        # 生成布局
        output_path, layout_data = engine.generate_layout(
            protocol=protocol,
            output_dir=output_dir
        )
        
        # 将protocol文件复制到输出目录
        output_subdir = Path(output_path).parent
        protocol_dest = output_subdir / Path(protocol_file).name
        shutil.copy2(protocol_file, protocol_dest)
        
        result['status'] = 'success'
        result['layout_file'] = output_path
        result['message'] = f'Successfully generated layout'
        result['object_count'] = len(layout_data.get('objects', []))
        print(f"[{Path(protocol_file).name}] ✓ 成功生成: {os.path.basename(output_path)}")
        
    except Exception as e:
        error_str = str(e)
        result['status'] = 'failed'
        result['error'] = error_str
        result['message'] = f'Failed: {error_str}'
        
        # 检查是否是内容审核错误
        is_content_policy_error = '内容违规' in error_str or 'sensitive_words_detected' in error_str or 'SelfHarm' in error_str
        
        if is_content_policy_error:
            result['error_type'] = 'content_policy'
            result['message'] = '内容审核误判（化学术语被误判为敏感内容）'
            print(f"[{Path(protocol_file).name}] ⚠ 内容审核误判: {result.get('experiment_name', 'Unknown')}")
        else:
            print(f"[{Path(protocol_file).name}] ✗ 失败: {error_str}")
        
        # 打印详细错误信息到文件
        error_log = os.path.join(output_dir, f'error_{Path(protocol_file).stem}.log')
        with open(error_log, 'w', encoding='utf-8') as f:
            f.write(f"Protocol File: {protocol_file}\n")
            f.write(f"Experiment Name: {result.get('experiment_name', 'Unknown')}\n")
            f.write(f"Error Type: {'Content Policy Violation (False Positive)' if is_content_policy_error else 'Other Error'}\n")
            f.write(f"Error: {error_str}\n\n")
            f.write(traceback.format_exc())
        result['error_log'] = error_log
    
    return result


def generate_single_layout(args: Tuple[str, str, str, Dict]) -> Dict:
    """
    生成单个 protocol 的布局（带重试机制）
    
    Args:
        args: (protocol_file, output_dir, asset_library_path, llm_config)
    
    Returns:
        结果字典，包含状态和信息
    """
    protocol_file, output_dir, asset_library_path, llm_config = args
    
    MAX_RETRIES = 5
    last_result = None
    
    for attempt in range(1, MAX_RETRIES + 1):
        result = generate_single_layout_no_retry(
            protocol_file, output_dir, asset_library_path, llm_config, attempt
        )
        
        if result['status'] == 'success':
            if attempt > 1:
                print(f"[{Path(protocol_file).name}] ✓ 重试成功 (第 {attempt} 次尝试)")
            return result
        
        last_result = result
        
        # 如果还有重试机会，显示重试信息
        if attempt < MAX_RETRIES:
            print(f"[{Path(protocol_file).name}] ⟳ 重试 {attempt}/{MAX_RETRIES}: {result.get('error', 'Unknown error')[:100]}")
        else:
            print(f"[{Path(protocol_file).name}] ✗ 失败 (已重试 {MAX_RETRIES} 次)")
    
    return last_result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='批量并行生成初始布局')
    parser.add_argument(
        '--workers',
        type=int,
        default=40,
        help='并行处理的数量 (default: 5)'
    )
    parser.add_argument(
        '--input-dir',
        type=str,
        default='DATA/protocols_batchv2_10',
        help='输入目录，包含 protocol 文件 (default: DATA/protocols_batchv2_10)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='OUTPUT/llm_layouts_1230',
        help='输出目录 (default: OUTPUT/llm_layouts_1230)'
    )
    parser.add_argument(
        '--asset-library',
        type=str,
        default='assets_annotated.json',
        help='资产库文件路径 (default: assets_annotated.json)'
    )
    parser.add_argument(
        '--model',
        type=str,
        default='claude-sonnet-4-5-20250929',
        help='LLM 模型 (default: claude-sonnet-4-5-20250929)'
    )
    parser.add_argument(
        '--temperature',
        type=float,
        default=0.7,
        help='LLM temperature (default: 0.7, higher for more diverse initial layouts with room for optimization)'
    )
    
    args = parser.parse_args()
    
    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 构建资产库路径
    asset_library_path = args.asset_library
    if not Path(asset_library_path).is_absolute():
        asset_library_path = project_root / asset_library_path
    
    if not Path(asset_library_path).exists():
        print(f"✗ 错误: 资产库文件不存在: {asset_library_path}")
        sys.exit(1)
    
    # 根据模型类型设置合适的max_tokens
    def get_max_tokens_for_model(model_name: str) -> int:
        """根据模型名称返回合适的max_tokens值"""
        model_lower = model_name.lower()
        if "gpt-4o" in model_lower:
            return 16384  # GPT-4o系列最大支持16384
        elif "gpt-4" in model_lower or "gpt-3.5" in model_lower:
            return 16384  # GPT-4和GPT-3.5系列通常也是16384
        elif "gemini" in model_lower:
            return 65536  # Gemini模型最大支持65536
        elif "claude" in model_lower:
            return 100000  # Claude模型支持更大的值
        else:
            # 默认使用较小值以避免错误
            return 16384
    
    # LLM 配置
    max_tokens = get_max_tokens_for_model(args.model)
    llm_config = {
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": max_tokens
    }
    print(f"使用模型: {args.model}, max_tokens: {max_tokens}")
    
    # 查找所有 protocol 文件
    print(f"查找 protocol 文件: {args.input_dir}")
    protocol_files = find_protocol_files(args.input_dir)
    
    if not protocol_files:
        print(f"✗ 错误: 在 {args.input_dir} 中未找到 protocol 文件")
        sys.exit(1)
    
    print(f"✓ 找到 {len(protocol_files)} 个 protocol 文件")
    
    # 准备任务列表
    tasks = []
    for protocol_file in protocol_files:
        tasks.append((
            protocol_file,
            args.output_dir,
            str(asset_library_path),
            llm_config
        ))
    
    print(f"\n开始批量生成 {len(tasks)} 个布局")
    print(f"并行数量: {args.workers}")
    print(f"输出目录: {args.output_dir}")
    print(f"资产库: {asset_library_path}")
    print("=" * 80)
    
    # 并行处理
    start_time = datetime.now()
    results = []
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # 提交所有任务
        future_to_file = {
            executor.submit(generate_single_layout, task): Path(task[0]).name 
            for task in tasks
        }
        
        # 收集结果
        completed = 0
        for future in as_completed(future_to_file):
            protocol_name = future_to_file[future]
            try:
                result = future.result()
                results.append(result)
                completed += 1
                print(f"进度: {completed}/{len(tasks)} 完成")
            except Exception as e:
                print(f"[{protocol_name}] ✗ 处理异常: {str(e)}")
                results.append({
                    'protocol_file': protocol_name,
                    'status': 'error',
                    'error': str(e)
                })
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # 统计结果
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = sum(1 for r in results if r['status'] == 'failed')
    error_count = sum(1 for r in results if r['status'] == 'error')
    content_policy_count = sum(1 for r in results if r.get('error_type') == 'content_policy')
    
    # 保存结果摘要
    summary = {
        'timestamp': datetime.now().isoformat(),
        'total_protocols': len(tasks),
        'success': success_count,
        'failed': failed_count,
        'errors': error_count,
        'content_policy_violations': content_policy_count,
        'duration_seconds': duration,
        'workers': args.workers,
        'input_dir': args.input_dir,
        'output_dir': args.output_dir,
        'asset_library': str(asset_library_path),
        'llm_config': llm_config,
        'results': results
    }
    
    summary_file = os.path.join(args.output_dir, f'batch_summary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    # 打印总结
    print("\n" + "=" * 80)
    print("批量生成完成！")
    print("=" * 80)
    print(f"总计: {len(tasks)} 个 protocol")
    print(f"✓ 成功: {success_count}")
    print(f"✗ 失败: {failed_count}")
    print(f"✗ 错误: {error_count}")
    if content_policy_count > 0:
        print(f"⚠ 内容审核误判: {content_policy_count} (化学术语被误判为敏感内容)")
    print(f"耗时: {duration:.2f} 秒 ({duration/60:.2f} 分钟)")
    if len(tasks) > 0:
        print(f"平均: {duration/len(tasks):.2f} 秒/布局")
    print(f"\n结果摘要: {summary_file}")
    print(f"输出目录: {args.output_dir}")
    
    # 列出失败的 protocol
    if failed_count > 0:
        print("\n失败的 protocol:")
        for r in results:
            if r['status'] == 'failed':
                error_type = r.get('error_type', '')
                if error_type == 'content_policy':
                    print(f"  - {Path(r['protocol_file']).name}: ⚠ 内容审核误判")
                else:
                    print(f"  - {Path(r['protocol_file']).name}: {r.get('message', 'Unknown error')}")
    
    return 0 if failed_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

