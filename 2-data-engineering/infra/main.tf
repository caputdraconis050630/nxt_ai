############################## IAM Roles ##############################

resource "aws_iam_role" "data_pipeline_role" {
  name = "${var.name}-pipeline-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          AWS = data.aws_caller_identity.current.arn
        }
      }
    ]
  })
}

############################## OpenSearch ##############################

resource "aws_opensearchserverless_security_policy" "network" {
  name = "${var.name}-network"
  type = "network"
  policy = jsonencode([
    {
      Rules = [{
        ResourceType = "collection",
        Resource     = ["collection/${var.name}"]
      }],
      AllowFromPublic = true
    }
  ])
}

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "${var.name}-encryption"
  type = "encryption"
  policy = jsonencode({
    Rules = [{
      ResourceType = "collection",
      Resource     = ["collection/${var.name}"]
    }],
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_access_policy" "data" {
  name = "${var.name}-data"
  type = "data"
  policy = jsonencode([
    {
      Description = "Data pipeline + local access",
      Principal = [
        aws_iam_role.data_pipeline_role.arn,
        data.aws_caller_identity.current.arn
      ],
      Rules = [
        {
          ResourceType = "collection",
          Resource     = ["collection/${var.name}"],
          Permission = [
            "aoss:CreateCollectionItems",
            "aoss:UpdateCollectionItems",
            "aoss:DescribeCollectionItems",
            "aoss:DeleteCollectionItems"
          ]
        },
        {
          ResourceType = "index",
          Resource     = ["index/${var.name}/*"],
          Permission = [
            "aoss:CreateIndex",
            "aoss:UpdateIndex",
            "aoss:DescribeIndex",
            "aoss:WriteDocument",
            "aoss:ReadDocument"
          ]
        }
      ]
    }
  ])
}

resource "aws_iam_role_policy" "pipeline_aoss_api" {
  name = "${var.name}-pipeline-aoss-api"
  role = aws_iam_role.data_pipeline_role.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = ["aoss:APIAccessAll"],
      Resource = [aws_opensearchserverless_collection.collection.arn]
    }]
  })
}

data "aws_caller_identity" "current" {}

resource "aws_opensearchserverless_collection" "collection" {
  name = var.name
  type = "VECTORSEARCH"
  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
    aws_opensearchserverless_access_policy.data,
  ]
}

resource "time_sleep" "wait_for_aoss" { # 컬렉션 생성 후 60초 대기
  depends_on = [
    aws_opensearchserverless_collection.collection,
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
    aws_opensearchserverless_access_policy.data,
  ]
  create_duration = "60s"
}

variable "embedding_dimension" {
  type    = number
  default = 1024 # Sentence transformers default
}

resource "null_resource" "create_vector_index" {
  depends_on = [time_sleep.wait_for_aoss]

  triggers = {
    endpoint = aws_opensearchserverless_collection.collection.collection_endpoint
    index    = "${var.name}-index"
    dim      = tostring(var.embedding_dimension)
    region   = var.region
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-lc"]
    command     = <<-EOB
      set -euo pipefail
    VENV_DIR="${path.module}/.venv_aoss"
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --quiet --upgrade pip
    pip install --quiet boto3==1.34.162 opensearch-py==2.6.0 requests-aws4auth==1.2.3

    python - <<'PY'
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

REGION   = "${var.region}"
ENDPOINT = "${aws_opensearchserverless_collection.collection.collection_endpoint}"
HOST     = ENDPOINT.replace("https://","").split("/")[0]
INDEX    = "${var.name}-index"
DIM      = int("${var.embedding_dimension}")

session = boto3.Session()
auth    = AWSV4SignerAuth(session.get_credentials(), REGION, "aoss")
client  = OpenSearch(
    hosts=[{"host": HOST, "port": 443}],
    http_auth=auth, use_ssl=True, verify_certs=True,
    connection_class=RequestsHttpConnection,
)

def create_index():
    body = {
      "settings": {
        "index": {
          "knn": True,
          "knn.algo_param.ef_search": 128
        }
      },
      "mappings": {
        "properties": {
          "vector_field": {
            "type": "knn_vector",
            "dimension": DIM,
            "method": {
              "engine": "faiss",
              "name": "hnsw",
              "space_type": "cosinesimil",
              "parameters": {"m": 16, "ef_construction": 128}
            }
          },
          "text": { "type": "text", "analyzer": "standard" },
          "metadata": {
            "type": "object",
            "dynamic": True,
            "properties": {
              "title":        { "type": "text",    "analyzer": "standard" },
              "keywords":     { "type": "keyword" },
              "summary":      { "type": "text",    "analyzer": "standard" },
              "source_type":  { "type": "keyword" },
              "source_url":   { "type": "keyword" },
              "chunk_index":  { "type": "integer" },
              "parent_doc_id":{ "type": "keyword" },
              "created_at":   { "type": "date" }
            }
          }
        }
      }
    }
    resp = client.indices.create(index=INDEX, body=body)
    print("created:", resp)

exists = client.indices.exists(index=INDEX)
if not exists:
    create_index()
else:
    mapping = client.indices.get_mapping(index=INDEX)
    props = mapping.get(INDEX, {}).get("mappings", {}).get("properties", {})
    method = (props.get("vector_field") or {}).get("method") or {}
    engine = method.get("engine")
    metadata_type = (props.get("metadata") or {}).get("type")
    has_text = "text" in props
    ok = (engine == "faiss") and (metadata_type == "object") and has_text
    if not ok:
        print(f"recreating index: engine={engine}, metadata_type={metadata_type}, has_text={has_text}")
        client.indices.delete(index=INDEX)
        create_index()
    else:
        print("index already exists with FAISS + metadata=object + text field; OK")
PY
    deactivate
  EOB
  }
}
