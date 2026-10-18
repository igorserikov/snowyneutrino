terraform {
  required_version = ">= 1.5.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "4.6.0"
    }
  }
}

variable "docker_host" {
  type = string
}

provider "docker" {
  host = var.docker_host
}

variable "trino_version" {
  type = string
}

variable "catalog_path" {
  type = string
}

resource "docker_image" "trino" {
  name         = "trinodb/trino:${var.trino_version}"
  keep_locally = true
}

resource "docker_container" "trino" {
  name  = "snowtrino-local-trino"
  image = docker_image.trino.image_id

  ports {
    ip       = "127.0.0.1"
    external = 8080
    internal = 8080
  }

  volumes {
    host_path      = var.catalog_path
    container_path = "/etc/trino/catalog"
    read_only      = true
  }
}

output "endpoint" {
  value = "http://127.0.0.1:8080"
}
