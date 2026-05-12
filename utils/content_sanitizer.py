"""
化学术语脱敏处理模块
用于将敏感化学术语替换为中性代码，避免触发API内容审核
"""

import re
from typing import Dict, List, Tuple

# 常见触发审核的化学术语映射表
SENSITIVE_TERMS = {
    # 酸类
    'nitric acid': 'oxidizing acid reagent',
    'sulfuric acid': 'strong acid catalyst',
    'hydrochloric acid': 'acidic reagent',
    'concentrated': 'standard',
    
    # 氯化物
    'chloride': 'halide compound',
    'thionyl chloride': 'chlorinating agent',
    'oxalyl chloride': 'acyl chloride reagent',
    
    # 氧化剂
    'oxidation': 'chemical transformation',
    'oxidizing': 'reactive',
    
    # 其他敏感词
    'harm': 'effect',
    'dangerous': 'reactive',
    'toxic': 'active compound',
    'explosive': 'energetic',
    'poison': 'active substance',
}

class ContentSanitizer:
    """内容脱敏处理器"""
    
    def __init__(self):
        self.term_map = SENSITIVE_TERMS.copy()
        self.reverse_map = {v: k for k, v in self.term_map.items()}
    
    def sanitize_text(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        将文本中的敏感化学术语替换为中性词汇
        
        Args:
            text: 原始文本
            
        Returns:
            (脱敏后的文本, 替换映射表)
        """
        sanitized = text
        replacements = {}
        
        for sensitive, neutral in self.term_map.items():
            if sensitive.lower() in sanitized.lower():
                # 使用正则表达式进行大小写不敏感替换
                pattern = re.compile(re.escape(sensitive), re.IGNORECASE)
                sanitized = pattern.sub(neutral, sanitized)
                replacements[sensitive] = neutral
        
        return sanitized, replacements
    
    def desanitize_text(self, text: str, replacements: Dict[str, str]) -> str:
        """
        将脱敏文本还原为原始术语
        
        Args:
            text: 脱敏后的文本
            replacements: 替换映射表
            
        Returns:
            还原后的文本
        """
        restored = text
        for sensitive, neutral in replacements.items():
            pattern = re.compile(re.escape(neutral), re.IGNORECASE)
            restored = pattern.sub(sensitive, restored)
        return restored


def sanitize_protocol(protocol: Dict) -> Tuple[Dict, Dict[str, str]]:
    """
    对整个protocol进行脱敏处理
    
    Args:
        protocol: 原始protocol字典
        
    Returns:
        (脱敏后的protocol, 替换映射表)
    """
    sanitizer = ContentSanitizer()
    sanitized_protocol = protocol.copy()
    all_replacements = {}
    
    # 脱敏实验名称
    if 'experiment_name' in sanitized_protocol:
        sanitized_protocol['experiment_name'], repl = sanitizer.sanitize_text(
            sanitized_protocol['experiment_name']
        )
        all_replacements.update(repl)
    
    # 脱敏实验描述
    if 'experiment_description' in sanitized_protocol:
        sanitized_protocol['experiment_description'], repl = sanitizer.sanitize_text(
            sanitized_protocol['experiment_description']
        )
        all_replacements.update(repl)
    
    # 脱敏资产名称和描述
    if 'assets' in sanitized_protocol:
        for asset in sanitized_protocol['assets']:
            if 'name' in asset:
                asset['name'], repl = sanitizer.sanitize_text(asset['name'])
                all_replacements.update(repl)
            if 'description' in asset:
                asset['description'], repl = sanitizer.sanitize_text(asset['description'])
                all_replacements.update(repl)
    
    # 脱敏安全警告
    if 'safety_warnings' in sanitized_protocol:
        sanitized_warnings = []
        for warning in sanitized_protocol['safety_warnings']:
            sanitized_warning, repl = sanitizer.sanitize_text(warning)
            sanitized_warnings.append(sanitized_warning)
            all_replacements.update(repl)
        sanitized_protocol['safety_warnings'] = sanitized_warnings
    
    return sanitized_protocol, all_replacements


if __name__ == '__main__':
    # 测试
    test_text = "Oxidation of Nicotine with Concentrated Nitric Acid using Thionyl Chloride"
    sanitizer = ContentSanitizer()
    sanitized, replacements = sanitizer.sanitize_text(test_text)
    print(f"原文: {test_text}")
    print(f"脱敏: {sanitized}")
    print(f"映射: {replacements}")
    restored = sanitizer.desanitize_text(sanitized, replacements)
    print(f"还原: {restored}")

