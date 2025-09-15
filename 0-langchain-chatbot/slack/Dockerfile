FROM public.ecr.aws/lambda/python:3.11

COPY requirements.txt ./
RUN python3.11 -m pip install -r requirements.txt

COPY handler.py rag_chain.py ./