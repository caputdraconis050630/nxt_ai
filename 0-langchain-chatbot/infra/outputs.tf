output "s3_bucket_name" {
  value = aws_s3_bucket.bucket.bucket
}

output "s3_bucket_arn" {
  value = aws_s3_bucket.bucket.arn
}

output "knowledge_base_role_arn" {
  value = aws_iam_role.knowledge_base_role.arn
}

output "knowledge_base_id" {
  value = aws_bedrockagent_knowledge_base.knowledge_base.id
}

output "knowledge_base_arn" {
  value = aws_bedrockagent_knowledge_base.knowledge_base.arn
}

output "data_source_id" {
  value = aws_bedrockagent_data_source.s3.data_source_id
}

output "opensearch_collection_arn" {
  value = aws_opensearchserverless_collection.collection.arn
}
