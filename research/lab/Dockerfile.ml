# The ML image (M1, results/modern_models_m1.md): the lab image plus torch's CPU wheels and the
# packages of the foundation and tabular models, every version pinned. Only the jobs that need it
# run it (research/ops/jobs.yaml, image pythia-lab-ml); the lab image itself stays as it is.
#   docker build -t pythia-lab -f research/lab/Dockerfile research/lab           (first, the base)
#   docker build -t pythia-lab-ml -f research/lab/Dockerfile.ml research/lab
# Model weights are not in the image: lab.models.factory.pinned_file downloads each pinned revision
# once into <data>/models/hub (PYTHIA_HUB_DIR) and reads it from there afterwards.
FROM pythia-lab

# The packages on top of requirements.txt, pinned: the numbers in results/modern_models_m1.md came from these.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 \
 && pip install --no-cache-dir \
    chronos-forecasting==2.3.2 timesfm==3.0.2 tabpfn==9.2.0 catboost==1.2.10 transformers==5.21.0 \
    accelerate==1.15.0 huggingface_hub==2.3.0 hf-xet==1.7.0 safetensors==0.8.0 tokenizers==0.23.3 \
    einops==0.8.2 pandas==3.1.0 skrub==0.10.1 pydantic==2.14.1 pydantic-settings==2.16.1 \
    pydantic_core==2.50.1 sympy==1.14.0 mpmath==1.3.0 filelock==3.32.3 fsspec==2026.7.0 \
    regex==2026.9.29 requests==2.34.2 psutil==7.2.2 graphviz==0.21 plotly==7.1.0 annotated-doc==0.0.5 \
    annotated-types==0.8.0 anyio==4.15.1 certifi==2026.10.23 charset-normalizer==3.5.2 click==8.5.0 h11==0.16.0 \
    httpcore2==2.16.0 httpx2==2.16.0 Jinja2==3.1.6 markdown-it-py==4.2.0 mdurl==0.1.2 pydot==4.0.1 \
    python-dotenv==1.2.4 rich==15.0.0 shellingham==1.5.4 truststore==0.10.5 typer==0.27.3 \
    typing-inspection==0.4.4 urllib3==2.8.0 \
 && python -c "import torch; assert not torch.cuda.is_available() and torch.__version__.endswith('+cpu')"
ENV PYTHIA_ML_THREADS=3 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
