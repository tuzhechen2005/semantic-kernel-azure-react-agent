---
id: availability_sets
title: Azure Virtual Machine Availability Sets
source: https://learn.microsoft.com/en-us/azure/virtual-machines/availability-set-overview
---

# Azure Virtual Machine Availability Sets

An availability set is a logical grouping of Azure virtual machines designed to reduce correlated failures.

Azure distributes virtual machines in an availability set across fault domains and update domains.

## Fault domains

A fault domain represents a group of virtual machines that share a common power source and network switch. Distributing virtual machines across fault domains reduces the chance that a localized hardware failure affects all application instances.

An availability set can have up to three fault domains.

## Update domains

An update domain represents a group of virtual machines and physical hardware that can be restarted at the same time during planned Azure maintenance.

Azure restarts only one update domain at a time. An availability set can have up to twenty update domains.

## Reliability characteristics

Applications should use two or more virtual machines in an availability set. Availability sets can provide lower VM-to-VM latency than availability zones because the virtual machines are placed closer together.

Availability sets do not provide the same level of resiliency as availability zones. They can still be affected by shared datacenter-level failures.

For workloads requiring protection from an entire datacenter failure, deploy multiple virtual machines across availability zones.