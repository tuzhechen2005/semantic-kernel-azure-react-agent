---
id: managed_disk_types
title: Azure Managed Disk Types
source: https://learn.microsoft.com/en-us/azure/virtual-machines/disks-types
version: 2026-08-30
updated: 2026-08-30
---

# Azure Managed Disk Types

Azure managed disks are block-level storage volumes managed by Azure and used with Azure virtual machines.

With managed disks, users specify the disk type and disk size. Azure manages the underlying storage accounts.

Azure provides five main managed disk types:

- Ultra Disk
- Premium SSD v2
- Premium SSD
- Standard SSD
- Standard HDD

## Ultra Disk

Ultra Disk is designed for IO-intensive and transaction-heavy workloads, such as SAP HANA and high-end SQL or Oracle databases.

It provides the highest IOPS and throughput among Azure managed disk types. Ultra Disk cannot be used as an operating system disk.

## Premium SSD v2

Premium SSD v2 is intended for production and performance-sensitive workloads that consistently require low latency, high IOPS, and high throughput.

Premium SSD v2 cannot be used as an operating system disk.

## Premium SSD

Premium SSD is intended for production and performance-sensitive workloads. It can be used as an operating system disk.

## Standard SSD

Standard SSD is suitable for web servers, lightly used enterprise applications, and development or test workloads. It provides more consistent performance than Standard HDD.

Standard SSD can be used as an operating system disk.

## Standard HDD

Standard HDD is intended for backup, non-critical workloads, and data that is accessed infrequently.

It offers lower cost but also lower performance than SSD-based disk types.

## Selecting a disk type

Choose a disk type based on:

- Required IOPS and throughput
- Latency requirements
- Workload criticality
- Whether the disk must be used as an operating system disk
- Cost constraints

For transaction-heavy databases, use Ultra Disk or Premium SSD v2 when their feature constraints are acceptable.

For production workloads, Premium SSD is a common choice.

For lightly used applications and development environments, Standard SSD is usually appropriate.

For backups and infrequently accessed, non-critical data, Standard HDD can reduce cost.
