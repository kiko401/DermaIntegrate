"""
DermaIntegrate AI 自定义异常定义。
"""


class DicomParseException(Exception):
    """DICOM 文件解析失败。"""
    pass


class ModelInferenceException(Exception):
    """模型推理异常（如 ONNX 加载失败、推理崩溃或生成非法结果）。"""
    pass


class DiagnosisUncertainException(Exception):
    """
    证据链断裂或诊断不确定。
    当多模态输入不足以支持置信诊断，或知识库离线导致无法生成有效结论时抛出。
    """
    pass
