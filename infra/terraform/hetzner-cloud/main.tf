terraform {
  required_providers {
    hcloud = { source = "hetznercloud/hcloud", version = "~> 1.49" }
  }
}
variable "hcloud_token" { sensitive = true }
variable "server_name" { default = "svs-micro-cell-1" }
variable "server_type" { default = "ccx43" }
variable "location" { default = "fsn1" }
variable "ssh_key_name" { default = "default" }
variable "volume_size_gb" { default = 500 }
provider "hcloud" { token = var.hcloud_token }
data "hcloud_ssh_key" "default" { name = var.ssh_key_name }
resource "hcloud_server" "svs" {
  name = var.server_name
  image = "ubuntu-24.04"
  server_type = var.server_type
  location = var.location
  ssh_keys = [data.hcloud_ssh_key.default.id]
  labels = { product = "svs", role = "micro-cell" }
}
resource "hcloud_volume" "svs_data" {
  name = "${var.server_name}-data"
  size = var.volume_size_gb
  server_id = hcloud_server.svs.id
  automount = true
  format = "ext4"
}
output "server_ipv4" { value = hcloud_server.svs.ipv4_address }
