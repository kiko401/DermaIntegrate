from agents.vlm_agent import VLMAgent
import os

# 随便找两张图测试即可（原图和刚才生成的占位热力图）
ORIGINAL_IMG = "./static/images/img_c9561c882d7344ad.png"
EVIDENCE_IMG = "./static/heatmaps/test_unet_mock.png"

if __name__ == "__main__":
    if not os.path.exists(EVIDENCE_IMG):
        print("❌ 找不到标记图，请先跑通上一个 LesionExtractor 的测试")
    elif not os.path.exists(ORIGINAL_IMG):
        print("❌ 找不到原图，请确认路径")
    else:
        agent = VLMAgent()
        # 因为 .env 里 USE_MOCK_VLM=true，这里会直接返回 Mock 数据
        result = agent.analyze(ORIGINAL_IMG, EVIDENCE_IMG)
        print("✅ VLM 分析结果（Mock模式）：")
        print(result)