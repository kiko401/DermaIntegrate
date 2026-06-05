class DicomParseException(Exception):
    """DICOM解析失败异常"""
    pass

class ModelInferenceException(Exception):
    """模型推理失败异常（如视觉证据提取失败）"""
    pass

class DiagnosisUncertainException(Exception):
    """证据链断裂异常（如视觉定位或RAG关键组件缺失）"""
    pass