# S3 Bucket
resource "aws_s3_bucket" "bucket" {
  bucket = "${var.prefix}-bucket"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "public_access_block" {
  bucket                  = aws_s3_bucket.bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_role" "knowledge_base_role" {
  name               = "${var.prefix}-knowledge-base-role"
  assume_role_policy = data.aws_iam_policy_document.knowledge_base_trust.json
}

data "aws_iam_policy_document" "knowledge_base_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "kb_bedrock_invoke" {
  name = "${var.name}-kb-bedrock-invoke"
  role = aws_iam_role.knowledge_base_role.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = [
        "bedrock:InvokeModel"
      ],
      Resource = [
        "arn:aws:bedrock:ap-northeast-2::foundation-model/amazon.titan-embed-text-v2:0"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "knowledge_base_s3_read" {
  name = "${var.prefix}-knowledge-base-s3-read"
  role = aws_iam_role.knowledge_base_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource = [
          "arn:aws:s3:::${aws_s3_bucket.bucket.bucket}/*",
          "arn:aws:s3:::${aws_s3_bucket.bucket.bucket}"
        ]
      }
    ]
  })
}

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
resource "aws_iam_role_policy" "kb_aoss_api" {
  name = "${var.name}-kb-aoss-api"
  role = aws_iam_role.knowledge_base_role.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = ["aoss:APIAccessAll"],
      Resource = [aws_opensearchserverless_collection.collection.arn]
    }]
  })
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

data "aws_caller_identity" "current" {}

resource "aws_opensearchserverless_access_policy" "data" {
  name = "${var.name}-data"
  type = "data"
  policy = jsonencode([
    {
      Description = "KB + local provisioner access",
      Principal = [
        aws_iam_role.knowledge_base_role.arn,
        data.aws_caller_identity.current.arn
      ],
      Rules = [
        {
          ResourceType = "collection",
          Resource     = ["collection/${var.name}"],
          Permission   = [
            "aoss:CreateCollectionItems",
            "aoss:UpdateCollectionItems",
            "aoss:DescribeCollectionItems",
            "aoss:DeleteCollectionItems"
          ]
        },
        {
          ResourceType = "index",
          Resource     = ["index/${var.name}/*"],
          Permission   = [
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

resource "aws_opensearchserverless_collection" "collection" {
  name = var.name
  type = "VECTORSEARCH"
  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
    aws_opensearchserverless_access_policy.data,
  ]
}

resource "time_sleep" "wait_for_aoss" { # 컬렉션 생성 후 60초 대기하게
  depends_on = [
    aws_opensearchserverless_collection.collection,
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
    aws_opensearchserverless_access_policy.data,
  ]
  create_duration = "60s"
}

variable "embedding_dimension" {
  type        = number
  description = "Embedding vector dimension (e.g., Titan v2 text = 1024)"
  default     = 1024
}

resource "null_resource" "create_vector_index" {
  depends_on = [time_sleep.wait_for_aoss]

  triggers = {
    endpoint = aws_opensearchserverless_collection.collection.collection_endpoint
    index    = "${var.name}-index"
    dim      = tostring(var.embedding_dimension) # titan embed text v2는 1024
    region   = var.region
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash","-lc"]
    command = <<-EOB
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
DIM      = int("1024")

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
          "embedding": {
            "type": "knn_vector",
            "dimension": DIM,
            "method": {
              "engine": "faiss",
              "name": "hnsw",
              "space_type": "l2",
              "parameters": { "m": 16, "ef_construction": 128 }
            }
          },
          "text": { "type": "text" },
          "metadata": { "type": "text" }
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
    method = (props.get("embedding") or {}).get("method") or {}
    engine = method.get("engine")
    metadata_type = (props.get("metadata") or {}).get("type")
    ok = (engine == "faiss") and (metadata_type == "text")
    if not ok:
        print(f"recreating index: engine={engine}, metadata_type={metadata_type}")
        client.indices.delete(index=INDEX)
        create_index()
    else:
        print("index already exists with FAISS + metadata=text; OK")
PY
    deactivate
  EOB
  }
}

resource "aws_bedrockagent_knowledge_base" "knowledge_base" {
  name     = "${var.name}-kb"
  role_arn = aws_iam_role.knowledge_base_role.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = var.embedding_model_id
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.collection.arn
      vector_index_name = "${var.name}-index"
      field_mapping {
        vector_field   = "embedding"
        text_field     = "text"
        metadata_field = "metadata"
      }
    }
  }
  depends_on = [
    aws_opensearchserverless_collection.collection,
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
    aws_opensearchserverless_access_policy.data,
    aws_iam_role_policy.kb_aoss_api,
    time_sleep.wait_for_aoss,
    aws_iam_role_policy.kb_bedrock_invoke,
  ]
}

resource "aws_bedrockagent_data_source" "s3" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.knowledge_base.id
  name              = "s3-docs"
  description       = "Slack threads (Markdown)"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn              = aws_s3_bucket.bucket.arn
      bucket_owner_account_id = var.account_id
      inclusion_prefixes      = [var.doc_prefix]
    }
  }

  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration {
        max_tokens         = 400
        overlap_percentage = 10
      }
    }
  }

  data_deletion_policy = "DELETE"

  depends_on = [
    aws_bedrockagent_knowledge_base.knowledge_base,
    aws_iam_role_policy.kb_bedrock_invoke,
  ]
}
