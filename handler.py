import runpod
from sentence_transformers import SentenceTransformer

# 모델을 전역에서 한 번만 로드 (메모리에 상주)
# Dockerfile 빌드 시점에 이미 다운로드되어 있어야 함
model = SentenceTransformer('intfloat/multilingual-e5-large-instruct')

def handler(event):
    """
    RunPod Serverless Handler
    Input format: {"input": {"texts": ["text1", "text2"], "is_query": true}}
    """
    input_data = event.get("input", {})
    texts = input_data.get("texts", [])
    is_query = input_data.get("is_query", True)
    
    if not texts:
        return []
    
    # E5 모델 특유의 프리픽스 처리
    prefix = "query: " if is_query else "passage: "
    processed_texts = [f"{prefix}{t}" for t in texts]
    
    # 임베딩 생성 (L2 Normalization 포함)
    embeddings = model.encode(processed_texts, normalize_embeddings=True)
    
    # JSON 직렬화를 위해 리스트로 변환하여 반환
    return embeddings.tolist()

runpod.serverless.start({"handler": handler})
