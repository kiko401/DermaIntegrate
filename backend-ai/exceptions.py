"""
DermaIntegrate AI 自定义异常定义。
定义了业务逻辑处理过程中的特定错误类型。
"""


class DicomParseException(Exception):
    """
    DICOM 解析异常。

    当读取 DICOM 文件失败、元数据缺失或色彩转码过程出错时抛出。
    通常会导致任务状态标记为 "failed"。
    """
    pass


class ModelInferenceException(Exception):
    """
    模型推理异常。

    当视觉模型（ONNX Runtime）加载失败、推理过程崩溃或生成非法结果时抛出。
    此异常会触发 SSE 流中的 "error" 事件，并尝试降级至占位符逻辑（若已实现）。
    """
    pass


class DiagnosisUncertainException(Exception):
    """
    证据链断裂异常。

    当多模态输入数据不足以支持置信诊断，或关键组件（如 RAG 知识库）离线导致无法生成有效结论时抛出。
    用于防止系统输出低置信度的误导性建议。
    """
    pass