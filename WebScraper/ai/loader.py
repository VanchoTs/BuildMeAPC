import os
from llama_cpp import Llama, llama_cpp
from ai.llm_utils import get_llm_ctx


def load_llm():
    model_path = os.environ.get("LLM_MODEL_PATH", "models_data/mistral-7b.gguf")
    n_ctx = get_llm_ctx()
    n_threads = int(os.environ.get("LLM_THREADS", "6"))
    gpu_layers_env = os.environ.get("LLM_GPU_LAYERS")
    if gpu_layers_env is None or gpu_layers_env.lower() == "auto":
        try:
            n_gpu_layers = -1 if llama_cpp.llama_supports_gpu_offload() else 0
        except Exception:
            n_gpu_layers = 0
    else:
        n_gpu_layers = int(gpu_layers_env)
    main_gpu = int(os.environ.get("LLM_MAIN_GPU", "0"))
    n_batch = int(os.environ.get("LLM_BATCH", "512"))
    n_ubatch = int(os.environ.get("LLM_UBATCH", "512"))

    return Llama(
        model_path=model_path,
        n_ctx=n_ctx,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers,
        main_gpu=main_gpu,
        n_batch=n_batch,
        n_ubatch=n_ubatch,
    )
