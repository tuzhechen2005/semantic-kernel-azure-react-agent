---
id: availability_zones
title: Azure Availability Zones
source: https://learn.microsoft.com/en-us/azure/reliability/availability-zones-overview
version: 2026-08-30
updated: 2026-08-30
---

# Azure Availability Zones

Azure availability zones are physically separate groups of datacenters within an Azure region. Each zone has independent power, cooling, and networking infrastructure.

Availability zones help protect applications and data from failures that affect an individual datacenter.

## Zonal deployments

A zonal resource is deployed into a specific availability zone selected by the user.

A single virtual machine placed in one zone is not resilient to a complete zone outage. To improve resiliency, deploy multiple virtual machines across two or more availability zones and distribute application traffic between them.

## Zone-redundant deployments

Zone-redundant services distribute or replicate resources across multiple availability zones. Azure manages the distribution between zones for supported services.

## Availability zones and virtual machines

Availability zones provide stronger fault isolation than availability sets because different zones use physically separate datacenters.

For Azure virtual machines, availability zones are appropriate when the workload requires protection against datacenter-level power, cooling, or networking failures.

Zone support depends on the Azure region and the selected virtual machine size. Before deployment, verify that both the region and VM SKU support availability zones.

## Comparison with availability sets

Availability sets distribute virtual machines across fault domains and update domains within a datacenter infrastructure.

Availability zones distribute virtual machines across physically separate datacenters within the same Azure region.

Availability sets can offer lower VM-to-VM latency, while availability zones provide greater protection from datacenter-level failures.
