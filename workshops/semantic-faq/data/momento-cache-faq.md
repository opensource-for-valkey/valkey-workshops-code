## Frequently Asked Questions

**What is the difference between Flex and Cluster?**

Both are fully managed and provide dedicated Valkey capacity. Flex abstracts cluster topology so that you specify capacity in GiB. Cluster exposes the instance type, shard count, replicas per shard, and zones directly.

**What is a Capacity Pool?**

A Capacity Pool is the dedicated Valkey capacity you provision and the product's isolation boundary. Momento manages the underlying cluster, and one or more Databases use its compute and memory.

**Can I use my existing Valkey or Redis client?**

Yes. Connect a standard standalone-mode client through the Momento-managed gateway. Migration is an endpoint change rather than an application rewrite.

**How does Momento Cache pricing work?**

Flex starts at $13 per GB-month of physical Valkey storage in us-east-1. A Flex pool configured with 3-GiB and two replicas per shard consumes 9 GiB each hour. With the Performance family, this costs $0.243/hour or $174.96 for a 30-day (720-hour) month. Cluster applies a 25% surcharge to the cloud provider's list price for deployed instances. For example, in us-east-1, one t4g.micro node with one primary shard and zero replicas costs $0.0105/hour for capacity, or $7.56 for a 30-day (720-hour) month. The Momento platform includes 200 GiB per month of ingress and egress data transfer across all qualifying Momento services. Additional Momento Cache data transfer costs $0.05/GiB.

**How should I organize Databases across pools?**

Group workloads that can share compute and memory on one pool. Put latency-sensitive, business-critical, or mutually isolated workloads on separate pools so they do not contend with each other.
