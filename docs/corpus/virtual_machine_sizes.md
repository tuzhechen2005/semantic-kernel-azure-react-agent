---
id: virtual_machine_sizes
title: Azure Virtual Machine Sizes Overview
source: https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview
version: 2026-08-30
updated: 2026-08-30
---

# Azure Virtual Machine Sizes Overview

An Azure virtual machine size defines available compute resources such as virtual CPUs, memory, temporary storage, and network capacity.

## Size families

General-purpose sizes balance CPU and memory. Compute-optimized sizes provide a higher CPU-to-memory ratio, while memory-optimized sizes provide more memory relative to CPU. Storage-optimized and GPU families target different workload needs.

## Selection constraints

Size availability varies by region and availability zone. Subscription quotas can also prevent deployment even when a size is offered in a region.

## Resizing

Changing a VM size can require a restart. If the requested size is not available on the current hardware cluster, deallocation may be required before resizing.
