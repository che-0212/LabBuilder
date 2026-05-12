"""
RAGflow客户端集成模块

用于从RAGflow知识库检索相关信息，增强protocol生成。
"""

from typing import List, Optional
from ragflow_sdk import RAGFlow


class RAGflowClient:
    """RAGflow客户端，用于检索知识库"""
    
    def __init__(self, api_key: str, base_url: str = "http://localhost:9380"):
        """
        初始化RAGflow客户端
        
        Args:
            api_key: RAGflow API密钥
            base_url: RAGflow服务地址，默认http://localhost:9380
        """
        self.api_key = api_key
        self.base_url = base_url
        self.rag_object = RAGFlow(api_key=api_key, base_url=base_url)
        self._dataset_cache = None
    
    def get_dataset_by_name(self, dataset_name: str):
        """
        根据名称获取知识库
        
        Args:
            dataset_name: 知识库名称
            
        Returns:
            DataSet对象，如果未找到返回None
        """
        try:
            datasets = self.rag_object.list_datasets(name=dataset_name)
            if datasets and len(datasets) > 0:
                return datasets[0]
            return None
        except Exception as e:
            raise Exception(f"获取知识库失败: {str(e)}")
    
    def retrieve(self, 
                 question: str,
                 dataset_name: str = "protocol",
                 page_size: int = 5,
                 similarity_threshold: float = 0.2,
                 top_k: int = 1024) -> List[dict]:
        """
        从知识库检索相关信息
        
        Args:
            question: 检索问题/查询
            dataset_name: 知识库名称，默认"protocol"
            page_size: 返回的chunk数量，默认5
            similarity_threshold: 相似度阈值，默认0.2
            top_k: 参与向量计算的chunk数量，默认1024
            
        Returns:
            检索到的chunk列表，每个chunk包含content、similarity等信息
        """
        try:
            # 获取知识库
            dataset = self.get_dataset_by_name(dataset_name)
            if dataset is None:
                raise Exception(f"未找到名为 '{dataset_name}' 的知识库")
            
            # 检索chunks (按照实际SDK代码：dataset_ids是第一个位置参数，question是第三个位置参数)
            chunks = self.rag_object.retrieve(
                dataset_ids=[dataset.id],
                document_ids=None,
                question=question,
                page_size=page_size,
                similarity_threshold=similarity_threshold,
                top_k=top_k
            )
            
            # 转换为字典列表，便于使用
            result = []
            for chunk in chunks:
                result.append({
                    "content": chunk.content,
                    "similarity": chunk.similarity if hasattr(chunk, 'similarity') else None,
                    "vector_similarity": chunk.vector_similarity if hasattr(chunk, 'vector_similarity') else None,
                    "term_similarity": chunk.term_similarity if hasattr(chunk, 'term_similarity') else None,
                    "document_name": chunk.document_name if hasattr(chunk, 'document_name') else None,
                    "document_id": chunk.document_id if hasattr(chunk, 'document_id') else None,
                    "position": chunk.position if hasattr(chunk, 'position') else None
                })
            
            return result
            
        except Exception as e:
            raise Exception(f"RAGflow检索失败: {str(e)}")
    
    def format_retrieved_context(self, chunks: List[dict]) -> str:
        """
        将检索到的chunks格式化为文本，用于添加到prompt中
        
        Args:
            chunks: 检索到的chunk列表
            
        Returns:
            格式化后的文本
        """
        if not chunks:
            return ""
        
        formatted_text = "## 相关协议知识库信息 (RAG检索结果)\n\n"
        formatted_text += "以下是从protocol知识库中检索到的相关信息，可用于指导协议生成：\n\n"
        
        for i, chunk in enumerate(chunks, 1):
            formatted_text += f"### 参考信息 {i}\n"
            formatted_text += f"**相似度**: {chunk.get('similarity', 'N/A'):.3f}\n" if chunk.get('similarity') else ""
            formatted_text += f"**来源文档**: {chunk.get('document_name', 'N/A')}\n" if chunk.get('document_name') else ""
            formatted_text += f"**内容**:\n{chunk.get('content', '')}\n\n"
        
        formatted_text += "**注意**: 请参考上述知识库信息，但确保生成的协议符合当前实验的具体要求。\n\n"
        
        return formatted_text

