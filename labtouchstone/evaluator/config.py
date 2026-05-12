"""
评估器配置文件
定义所有评分标准、阈值和权重
"""

# ===== 物理约束配置 =====

PHYSICAL_CONSTRAINTS = {
    'boundary': {
        'max_score': 12,  # 调整为12分
        'deduction_rules': {
            # (阈值cm, 扣分)
            'severe': (50, 6),     # 超出>50cm，扣6分
            'high': (20, 3),       # 超出20-50cm，扣3分
            'medium': (5, 1.5),    # 超出5-20cm，扣1.5分
            'low': (0, 0.3)        # 超出<5cm，扣0.3分
        }
    },
    'collision': {
        'max_score': 12,  # 调整为12分
        'deduction_rules': {
            # (重叠面积cm², 扣分)
            'severe': (100, 6),    # 重叠>100cm²，扣6分
            'high': (50, 4),       # 重叠50-100cm²，扣4分
            'medium': (10, 2),     # 重叠10-50cm²，扣2分
            'low': (0, 1)          # 重叠<10cm²，扣1分
        }
    },
    'height': {
        'max_score': 5,  # 调整为5分
        'expected_heights': {
            'floor': 0.0,  # 房间资产应该在地面
            'ExperimentalPlatform': 0.8,   # m
            'FumeHood': 0.8    # m
        },
        'tolerance': 0.01,  # 容差1cm
        'deduction_rules': {
            # (误差m, 扣分)
            'severe': (0.1, 1.0),  # 误差>10cm，扣1分
            'high': (0.05, 0.6),   # 误差5-10cm，扣0.6分
            'medium': (0.03, 0.4), # 误差3-5cm，扣0.4分
            'low': (0.01, 0.2)     # 误差1-3cm，扣0.2分
        }
    }
}

# ===== 化学约束配置 =====

CHEMICAL_CONSTRAINTS = {
    'C1': {
        'name': 'flammable_heat_separation',
        'description': '易燃物与热源分离',
        'weight': 5,  # 最高优先级安全约束
        'threshold': 100,  # cm（从80提高到100）
        'type': 'distance'
    },
    'C2': {
        'name': 'explosive_storage',
        'description': '爆炸物安全存储',
        'weight': 5,  # 最高优先级安全约束
        'required_location': 'cabinet',
        'type': 'location'
    },
    'C3': {
        'name': 'reagent_cabinet_storage',
        'description': '所有试剂需要存放在试剂柜',
        'weight': 5,  # 最高优先级安全约束
        'required_location': 'reagent_cabinet',
        'type': 'location'
    },
    'C4': {
        'name': 'glass_edge_avoidance',
        'description': '玻璃容器远离边缘',
        'weight': 3,  # 中等优先级
        'threshold': 30,  # cm
        'type': 'edge_distance'
    },
    'C5': {
        'name': 'incompatible_separation',
        'description': '不相容试剂分离',
        'weight': 4,  # 高优先级
        'threshold': 70,  # cm（从50提高到70）
        'type': 'distance'
    },
    'C6': {
        'name': 'acid_base_separation',
        'description': '酸碱分离',
        'weight': 4,  # 高优先级
        'threshold': 70,  # cm（从50提高到70）
        'type': 'distance'
    },
    'C7': {
        'name': 'oxidizer_organic_separation',
        'description': '氧化剂与有机物分离',
        'weight': 3,  # 中等优先级
        'threshold': 60,  # cm（从50提高到60）
        'type': 'distance'
    },
    'C8': {
        'name': 'metal_acid_separation',
        'description': '金属与酸分离',
        'weight': 2,  # 较低优先级
        'threshold': 80,  # cm（从60提高到80）
        'type': 'distance'
    },
    'C9': {
        'name': 'oxidizing_acid_reducing_salt_separation',
        'description': '氧化性酸与还原性盐分离',
        'weight': 2,  # 较低优先级
        'threshold': 120,  # cm（从100提高到120）
        'type': 'distance'
    },
    'C10': {
        'name': 'heat_source_zone',
        'description': '热源在实验区',
        'weight': 2,  # 较低优先级
        'required_zone': 'experimental',
        'type': 'zone'
    }
}

# ===== CSP满足度评分曲线 =====

def calculate_satisfaction(ratio):
    """
    根据实际值/期望值的比率计算满足度（严格版本）
    
    更严格的评分曲线：只有接近完全满足才能得高分
    
    Args:
        ratio: actual_value / required_value
    
    Returns:
        satisfaction: 0-1之间的满足度
    
    评分对照表：
        ratio=1.0  → 1.0  (完全满足)
        ratio=0.95 → 0.85
        ratio=0.9  → 0.7
        ratio=0.8  → 0.4
        ratio=0.7  → 0.28
        ratio=0.5  → 0.15
    """
    if ratio >= 1.0:
        # 完全满足
        return 1.0
    elif ratio >= 0.9:
        # 接近满足（90-100%），线性映射到0.7-1.0
        return 0.7 + (ratio - 0.9) / 0.1 * 0.3
    elif ratio >= 0.7:
        # 部分满足（70-90%），线性映射到0.2-0.7
        return 0.2 + (ratio - 0.7) / 0.2 * 0.5
    else:
        # 明显违反（<70%），严厉惩罚
        return ratio * 0.3

# ===== 语义评估配置 =====

SEMANTIC_EVALUATION = {
    'max_score': 30,
    'questions_count': 5,  # 改为5个问题
    'score_per_question': 6,  # 每题6分
    'category_distribution': {
        'layout': 1,    # 1题，6分
        'safety': 2,    # 2题，12分
        'workflow': 1,  # 1题，6分
        'aesthetics': 1 # 1题，6分
    }
}

# ===== LLM配置 =====

LLM_CONFIG = {
    'model': 'claude-sonnet-4-5-20250929',
    'temperature': 0.3,
    'max_tokens': 10000
    # timeout, retry_times等参数在ModelAPI中处理
}

# ===== 图片路径配置 =====

IMAGE_CONFIG = {
    'base_dir': './rendering_output',
    'views': ['top', 'north', 'south', 'east', 'west'],  # 匹配实际的view_xxx.png文件名
    'format': 'png'
}

# ===== 评分等级 =====

GRADING_SCALE = {
    'A': (90, 100),
    'B': (80, 89),
    'C': (70, 79),
    'D': (60, 69),
    'F': (0, 59)
}

PASS_THRESHOLD = 60  # 及格线

def get_grade(score):
    """根据分数获取等级"""
    for grade, (min_score, max_score) in GRADING_SCALE.items():
        if min_score <= score <= max_score:
            return grade
    return 'F'

# ===== 功能分区定义 =====

FUNCTIONAL_ZONES = {
    'background': (0.7, 1.0),      # 后30%
    'preparation': (0.4, 0.7),     # 中后30%
    'experimental': (0.1, 0.4),    # 中前30%
    'result': (0.0, 0.1)           # 前10%
}

