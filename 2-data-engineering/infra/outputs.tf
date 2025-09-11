output "opensearch_collection_arn" {
  value = aws_opensearchserverless_collection.collection.arn
}

output "opensearch_collection_endpoint" {
  value = aws_opensearchserverless_collection.collection.collection_endpoint
}

output "opensearch_dashboard_endpoint" {
  value = aws_opensearchserverless_collection.collection.dashboard_endpoint
}

output "opensearch_index_name" {
  value = "${var.name}-index"
}

output "data_pipeline_role_arn" {
  value = aws_iam_role.data_pipeline_role.arn
}
