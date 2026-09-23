# Amazon ElastiCache FAQs

## General

### What is Amazon ElastiCache?

Amazon ElastiCache is a serverless caching service that streamlines deployment, operation, and running of Valkey, Memcached, or Redis OSS caches in the cloud. ElastiCache improves application performance by serving data from RAM instead of slower disk-based databases, delivering microsecond latency with up to 99.99% availability SLA. The service offloads time-consuming tasks like management, monitoring, and operation of caches, enabling your engineering resources to focus on developing applications. Since it is fully compatible with Valkey, Memcached, and Redis OSS, all the code, applications, and popular tools you use today will work with the service. There are no upfront investments required, and you pay only for the resources you use.

### What is caching and how does it help my applications?

The caching provided by ElastiCache can be used to improve latency and throughput for many read-heavy application workloads (such as social networking, gaming, media sharing, and Q&A portals) or compute-intensive workloads (such as a recommendation engine). Caching improves application performance by storing critical pieces of data in memory for low-latency access. Cached information can include the results of I/O-intensive database queries or the results of computationally intensive calculations.

### What deployment options do I have for ElastiCache?

ElastiCache offers two deployment options: **serverless** and **node-based**.

- **Serverless** — Zero infrastructure management, zero downtime maintenance, and instant scaling to any application demand.
- **Node-based** — Select specific node types and sizes for fine-grained control over configuration and resource allocation. For users with fixed capacity needs and specific node type requirements.

### What does ElastiCache manage on my behalf?

As a fully managed service, ElastiCache handles complex, time-consuming administrative tasks so your team can focus on building and optimizing your application. It removes the undifferentiated heavy lifting of caching administrative tasks such as hardware provisioning, software patching, monitoring, and backup and recovery. ElastiCache publishes detailed CloudWatch metrics so you can set alarms for overloaded caches and respond quickly to issues. With ElastiCache Serverless, you don't have to worry about the underlying infrastructure.

### How does ElastiCache interact with other AWS services?

ElastiCache works as a front-end caching layer for AWS services like Amazon RDS, Amazon Aurora, Amazon DocumentDB, and Amazon DynamoDB, reducing database load and delivering microsecond read latency. The service can also be used to improve application performance in conjunction with Amazon EC2 and Amazon EMR.

### How am I billed for ElastiCache?

ElastiCache pricing depends on your deployment model:

- **ElastiCache Serverless** — Bills per GB of data stored and per ECPU consumed by your application, with no node-hour charges.
- **Node-based ElastiCache** — Bills per node-hour at rates that vary by instance type, with optional Reserved Node discounts for 1- or 3-year commitments.

Cross-Region data transfer for Global Datastore and S3 storage for backups beyond the free tier are billed separately.

### How do I select the right node type?

You don't need to get the number of nodes exactly right with ElastiCache, as you can quickly add or remove nodes later. You can also use ElastiCache Serverless to simplify running a highly available cache. Two inter-related aspects to consider:

1. The total memory required for your data to achieve your target cache-hit rate.
2. The number of nodes required to maintain acceptable application performance without overloading the database backend in the event of node failures.

For example, if your memory requirement is 13 GB, two `cache.m7g.large` nodes provide better fault tolerance than a single `cache.m7g.xlarge`.

### Can a cluster span multiple AZs?

Yes. When you create a cluster or add nodes, you can distribute nodes across multiple Availability Zones either by specifying the node counts in each AZ or selecting **Spread Nodes Across Zones**. If the cluster is in Amazon VPC, nodes can only be placed in AZs included in your cache subnet group.

---

## Performance

### What are the performance benefits of ElastiCache?

ElastiCache provides microsecond latency and scales to over billions of operations per second across hundreds of thousands of customers. For example, pairing ElastiCache with RDS for MySQL saves you up to 55% in costs while providing up to 80x faster read performance (versus RDS for MySQL alone). As traffic fluctuates, ElastiCache scales to hundreds of terabytes of data and billions of operations per second; with ElastiCache for Valkey you can reach up to 310 TiB of data in a single cluster, or 982 TiB with data tiering. ElastiCache also supports **semantic caching**, which stores and retrieves responses based on meaning rather than exact key matches, reducing the cost and latency of AI workloads.

### Does a failover affect latency between my application and the cache?

AWS Availability Zones within the same Region are engineered for low-latency network connectivity to other AZs in the same Region, so cross-AZ failover introduces negligible additional cache latency. For optimal performance, architect your application tier with redundancy across the same AZs as your ElastiCache nodes.

---

## Scalability / Serverless

### What is ElastiCache Serverless?

ElastiCache Serverless is the most automated deployment option for Amazon ElastiCache. It offers zero infrastructure management, zero downtime maintenance, instant scaling to any application demand, and pay-for-use billing. Each serverless cache runs in or across multiple Availability Zones and provides a **99.99% availability SLA**. ElastiCache Serverless supports:

- ElastiCache version 7.2+ for Valkey
- ElastiCache version 1.4.5+ for Memcached
- ElastiCache versions 4.0.10 to 7.1 for Redis OSS

### How do I migrate an existing ElastiCache workload to ElastiCache Serverless?

Change the Valkey, Memcached, or Redis OSS endpoint to your new ElastiCache Serverless cache endpoint in your application. You can migrate existing data by specifying the Amazon S3 location of a backup file.

### How does ElastiCache Serverless scale?

ElastiCache Serverless continuously monitors your cache's memory, compute, and network utilization to instantly scale. It scales without downtime or performance degradation by allowing the cache to scale up and initiating scale-out in parallel.

### How do I scale a node-based ElastiCache cluster?

- **Horizontally** — Add shards or nodes.
- **Vertically** — Change to a larger instance type.

Valkey and Redis OSS clusters support online resharding and online vertical scaling using read replicas, so you do not need to take the cluster offline. Memcached clusters support horizontal scaling by adding nodes and vertical scaling by changing the node type.

---

## Reliability

### What is durability for ElastiCache?

Durability allows you to use ElastiCache as a persistent data store with microsecond read latency. It provides data protection through a **Multi-AZ transactional log**, enabling fast recovery and restart. Two durability options:

- **Synchronous writes** — Designed for zero data loss with single-digit millisecond write latency.
- **Asynchronous writes** — Microsecond write latency at no additional cost; data loss bounded to up to 10 seconds in the rare event of a failure.

Use cases include knowledge bases for RAG applications, AI agent long-term memory, AI agent workflow state, payment tokenization, streaming metadata, gaming leaderboards/player state, and real-time inventory management.

### What is the difference between synchronous writes and asynchronous writes?

| Feature | Synchronous Writes | Asynchronous Writes |
|---|---|---|
| Persistence | Before responding to client | After responding to client |
| Write latency | Single-digit milliseconds | Microseconds |
| Read latency | Microseconds | Microseconds |
| Data loss risk | Designed for zero data loss | Up to 10 seconds in rare failure |
| Additional cost | Yes | No |

### How is durability different from Valkey and Redis OSS append-only file (AOF)?

ElastiCache uses a Multi-AZ transactional log to durably store data across multiple AZs. In contrast, AOF persists data in a file on a node's local disk in a single AZ. Even when AOF is enabled on replica nodes, replication between primary and replicas remains asynchronous, which can result in unbounded data loss and consistency issues during failover.

### What does it mean to run a node as a read replica?

A read replica creates a live, read-only copy of a primary instance kept synchronized through replication. The primary serves writes and reads; the replica serves exclusively read traffic and is also available as a warm standby. ElastiCache allows up to **five read replicas** per primary cache node. Read replicas are available for Valkey and Redis OSS engines only, not Memcached.

### When would I want to consider using a read replica?

- **Scaling beyond primary capacity** — Direct excess read traffic to one or more read replicas.
- **Serving reads during primary unavailability** — Direct read traffic to replicas during scheduled maintenance (data may be stale).
- **Data protection** — Promote a read replica in a different AZ to become the new primary in the event of failure.

### Can I create a read replica in another Region as my primary?

No. Read replicas can only be provisioned in any AZ within the same Region as your primary cache node. Use **Global Datastore** for cross-Region read replica clusters.

### What happens during failover and how long does it take?

ElastiCache flips the DNS record for your cache node to point at the read replica, which is promoted to become the new primary. A new healthy node joins the cluster within six minutes. For Global Datastore cross-Region failovers, promotion can complete in under one minute.

### What is Backup and Restore?

Backup and Restore creates snapshots of your ElastiCache cache and stores them in Amazon S3 in the same Region. Supported with ElastiCache for Valkey, ElastiCache for Redis OSS, and ElastiCache Serverless for Memcached.

- Initiate a backup any time or set a recurring daily backup with retention up to **35 days**.
- One free snapshot per active cache; additional storage at $0.085/GiB per month.
- Snapshots are compatible with the Redis OSS RDB file format.

### Can I use snapshots from one account to warm start a cluster in a different account?

Yes. Copy your snapshot into an authorized S3 bucket in the same Region, then grant cross-account bucket permissions to the other account.

### What happens to my snapshots if I delete my ElastiCache cache?

Manual snapshots are retained. You also have the option to create a final snapshot before the cache is deleted. Automatic cache snapshots are not retained.

### Can I restore a backup from ElastiCache for Redis OSS to ElastiCache for Valkey?

Yes. ElastiCache for Valkey can restore backups from any version of ElastiCache for Redis OSS, because both engines use the Redis RDB file format.

### What is ElastiCache Global Datastore?

Global Datastore is a feature of node-based ElastiCache that provides fully managed, fast, reliable, and security-focused cross-Region replication. You can write to your cache in one Region and have the data available for read in up to **two other cross-Region replica clusters**. Replication happens in under one second. Supported on ElastiCache version 7.2+ for Valkey and version 5.0.6+ for Redis OSS. Memcached does not offer Global Datastore. No premium charge to use Global Datastore.

### How many AWS Regions can I replicate to?

Up to **two secondary Regions** within a Global Datastore.

### Does ElastiCache automatically fail over a Global Datastore?

No. You must manually initiate the failover by promoting a secondary cluster. Promotion typically completes in less than one minute.

### What RPO and RTO can I expect with Global Datastore?

- **RPO** — Typically under one second.
- **RTO** — Typically under one minute.

ElastiCache does not provide an SLA for RPO and RTO; actual values depend on replication lag and network conditions.

### How is my data secured when using Global Datastore?

Global Datastore uses **encryption in transit** for cross-Region traffic. You can also encrypt primary and secondary caches using **encryption at rest**. Each primary and secondary cache can have a separate customer-managed AWS KMS key.

---

## Availability / Multi-AZ

### What is Multi-AZ for ElastiCache?

Multi-AZ replicates data across multiple Availability Zones and provides automatic failover if a primary node fails. All ElastiCache Serverless caches run Multi-AZ. An ElastiCache replication group consists of a primary and up to five read replicas. Multi-AZ is offered in ElastiCache for Valkey and Redis OSS. Memcached does not support replication or failover natively, so Multi-AZ is not offered for Memcached.

### What are the benefits of Multi-AZ and when should I use it?

- Enhanced availability — Node-based Redis OSS and Valkey deployments are eligible for the **99.99% availability SLA**.
- Less administration — Failover is automatic and requires no manual intervention.

---

## Security and Compliance

### What security controls exist for ElastiCache?

ElastiCache provides defense in depth across four layers:

1. **Encryption at rest** with AWS KMS
2. **Encryption in transit** using TLS
3. **Authentication** with AWS IAM
4. **Network access control** with Amazon EC2 security groups

You can also enable **Role-Based Access Control (RBAC)** for fine-grained permissions.

### How do I control access to ElastiCache?

- **Network layer** — VPC security groups and network ACLs act as firewalls. Access is turned off by default.
- **Identity layer** — IAM authentication and Valkey or Redis OSS RBAC control which users/roles can connect and which commands they can execute.

### Which compliance programs does ElastiCache support?

SOC 1, SOC 2, SOC 3, ISO, MTCS, C5, PCI DSS, HIPAA, and FedRAMP. A Business Associate Agreement (BAA) with AWS is required to process PHI under HIPAA.

### What does encryption at rest provide?

Protects data from unauthorized access during disk sync, backup, swap operations, and backups stored in Amazon S3. ElastiCache offers default (service-managed) encryption at rest and the ability to use your own customer-managed AWS KMS keys.

### What does encryption in transit provide?

Uses TLS to protect data between clients and ElastiCache, and between servers (primary and read replicas) within a cluster. ElastiCache manages TLS certificate issuance and renewal automatically.

---

## Cost Effective

### What is data tiering for ElastiCache?

Data tiering in node-based ElastiCache uses lower-cost NVMe SSDs in addition to memory. Ideal for workloads that regularly access up to 20% of their overall dataset. Runs on **R6gd nodes** with nearly 5x more total storage capacity, achieving over **60% savings** in price. Supported for ElastiCache versions 7.2+ for Valkey and 6.2+ for Redis OSS; not supported for Memcached.

### How does data tiering work?

Data tiering automatically moves the least recently used items from memory to locally attached NVMe SSDs when memory capacity is fully consumed. When an SSD-resident item is accessed, ElastiCache asynchronously moves it back to memory before serving the request.

### What performance can I expect with data tiering?

Assuming 500-byte string values, expect an additional ~300µs latency on average for requests to data stored on SSD versus data in memory. Requests for items already in memory see no latency penalty.

### Which ElastiCache features are supported with data tiering?

All Valkey and Redis OSS commands are supported. Most ElastiCache features work without modification. A small number of features have compatibility limitations.

### What are ElastiCache reserved nodes?

Reserved Instances (RIs) offer a significant discount over on-demand usage in exchange for a 1- or 3-year reservation. Three types: **All Upfront**, **No Upfront**, and **Partial Upfront**. You can purchase up to 300 reserved nodes per Region. ElastiCache Serverless is not compatible with reserved nodes.

### What happens to my Redis OSS reserved nodes if I upgrade to Valkey?

Your Redis OSS reservations automatically apply to Valkey nodes in the same instance family and Region. Since Valkey is priced 20% lower, you get **20% more capacity** at no additional cost. For example, a reservation for 5 `cache.r7g.2xlarge` Redis OSS nodes covers a sixth Valkey node of the same type.

### Does size flexibility apply to ElastiCache reserved nodes?

Yes. Reserved node rates apply automatically to usage of all sizes in the same node family and Region.

---

## Valkey Engine

### Why should I use ElastiCache for Valkey?

- Fully managed, open source Valkey under the Linux Foundation (no vendor lock-in)
- **99.99% availability SLA**
- **33% lower** Serverless pricing (minimum data storage of 100 MB, 90% lower than Redis OSS Serverless)
- **20% lower** per-node cost on node-based
- Faster scaling and 20% more memory efficiency versus Redis OSS

### How is ElastiCache for Valkey different from ElastiCache for Redis OSS?

1. Faster scaling and 20% more memory efficiency
2. Up to 33% lower (Serverless) and 20% lower (node-based) pricing
3. Uses Valkey under the Linux Foundation, avoiding vendor lock-in

### How do I upgrade from ElastiCache for Redis OSS to ElastiCache for Valkey?

Upgrade in-place without downtime in just a few clicks. You can upgrade from any supported Redis OSS version to any Valkey version. Upgrading from Redis OSS versions earlier than 5.0.6 may experience a failover time of 30–60 seconds. After upgrading to version 7.2 for Valkey, you can roll back to version 7.1 for Redis OSS.

### How can I migrate from self-managed Valkey or Redis OSS to ElastiCache for Valkey?

- **Online migration** — Replicate data into ElastiCache with minimal disruption.
- **Snapshot restore** — Take an RDB snapshot and restore it into ElastiCache for Valkey.

### Do reserved node discounts carry across all node sizes when I upgrade to Valkey?

Yes. Redis OSS reserved node discounts apply to Valkey nodes in the same instance family and Region, and size flexibility extends across all sizes. Your reservation covers **25% more Valkey capacity** than it did for Redis OSS.

---

## Memcached Engine

### How do I migrate from Memcached to ElastiCache?

ElastiCache is fully compatible with Memcached. Update your application's Memcached configuration file to include ElastiCache endpoints. Use **Auto Discovery** to enable automatic discovery of cache nodes when they are added to or removed from a cluster.

### Can I control when ElastiCache upgrades my Memcached engine version?

Yes. ElastiCache does not apply major or minor engine upgrades automatically. Security patches may be applied during your configured maintenance window.

### How do I specify which Memcached version my cluster should run?

Specify any currently supported version when creating a new cluster. Use the **Modify** option to upgrade, applying immediately or during the next maintenance window.

### Can I test my cluster against a new version before upgrading?

Yes. Create a new cluster with the new engine version and point your development or staging application to it for testing.

---

## Redis OSS Engine

### Will AWS continue to support ElastiCache for Redis OSS?

Yes. ElastiCache will continue to support previous versions of Redis OSS, including ElastiCache version 7.1 for Redis OSS. Older versions of all engines will be deprecated following a standard end-of-life process with advance notice.
