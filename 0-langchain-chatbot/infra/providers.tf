terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.11.0"
    }
    time = {
      source  = "hashicorp/time"
      version = ">= 0.13.0"
    }
  }

  required_version = ">= 1.8.0"
  backend "local" { path = "./terraform.tfstate" }
}

provider "aws" {
  region = var.region
}
