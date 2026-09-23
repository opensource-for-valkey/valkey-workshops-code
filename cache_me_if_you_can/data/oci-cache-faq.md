# OCI Cache FAQ

## General

**What is OCI Cache?**

OCI Cache is a high performance in-memory key-value store service, utilizing Valkey and Redis to enhance application performance by delivering ultra-fast data access. It speeds up data retrieval by accessing data stored in memory rather than performing disk operations on a database, thereby reducing the load on disk resources.

**What are the use cases?**

OCI Cache is ideal for applications requiring fast, real-time data delivery, such as ecommerce, financial services, real-time data analytics, ride-sharing, food delivery applications, gaming, and more. It works seamlessly with popular databases, such as MySQL and PostgreSQL, allowing you to choose your preferred database while benefiting from enhanced performance.

**What versions of Valkey and Redis does Oracle offer through OCI Cache?**

Currently, OCI Cache supports Valkey version 7.2 and 8.1. We are committed to broadening our offerings with more versions and supporting upgrades in the future. OCI Cache supports Redis version 7.0.5.

**What does Oracle manage in OCI Cache?**

Oracle simplifies the management of OCI Cache by automating cluster creation, ensuring high availability across availability domains or fault domains, managing automatic failover, and handling operating system patching, security updates, and resizing.

## Configuration

**What are flexible memory shapes?**

OCI Cache offers flexible memory shapes, allowing you to select the exact amount of memory needed for your cluster nodes. Unlike other solutions that may require you to overprovision memory, our service supports discrete memory values to prevent unnecessary resource allocation. Additionally, you can scale your cluster up or down on the fly, with up to 500 GB of memory per node.

**How many nodes can I provision?**

In a non-sharded cluster, you can provision up to five nodes per OCI Cache cluster for optimal replication and high availability, with a maximum of 40 nodes per tenancy. For a sharded cluster, you can provision up to 100 shards and up to five nodes per shard.

## Additional Details

**What about monitoring and metrics?**

OCI Cache provides comprehensive monitoring and metrics through standard OCI tools. You can track the health and performance of your cluster, monitor CPU and memory utilization, and set alarms and notifications for proactive scaling decisions.

**Is OCI Cache compliant with baseline industry standards and regulations?**

Yes, OCI Cache complies with all OCI baseline compliance programs, including FIPS, PCI, HIPAA, GDPR, SOC, and ISO.
