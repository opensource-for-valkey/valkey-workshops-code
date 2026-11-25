# OCI Cache workshop FAQ

These questions and answers were written for this workshop. They are original
teaching material, rather than a reproduction of Oracle's product FAQ. Oracle's
documentation is linked only to support the service configuration fact below.
The workshop uses a local Valkey server and does not provision OCI resources.

## Provider scope

**Why does this workshop include OCI Cache questions?**

The corpus contains several cache providers so you can test provider isolation.
A question about OCI Cache must retrieve an answer from `oci-cache-faq.md`.
Even when two questions have similar wording, the semantic cache must not reuse
an Amazon ElastiCache answer for an OCI Cache request.

**How many nodes does OCI Cache support in a non-sharded cluster?**

For non-sharded mode, Oracle's creation guide specifies one primary and zero to
four replicas, giving a cluster of one to five nodes. This answer applies to
non-sharded mode only. Check Oracle's current documentation before sizing a real
deployment, because sharded mode has different limits and configuration choices.
The local workshop does not create any of these managed-service nodes.

*Source: [Oracle, Creating an OCI Cache cluster](https://docs.oracle.com/en-us/iaas/Content/ocicache/createcluster.htm).*

**How should I check whether an answer came from OCI Cache?**

Inspect `source.provider` in the response. It should say `OCI Cache`, and the
source filename should be `oci-cache-faq.md`. The cache scope also needs to match
the requested provider. A high similarity score alone does not justify sharing
answers between providers.

## Corpus maintenance

**What happens when I update an OCI Cache FAQ answer?**

The application derives `corpus_version` from the names and bytes of every FAQ
file. Changing this file changes that version after the catalog reloads. The
cache checks the version before reusing an answer, so an answer from an older
corpus is rejected rather than silently returned.

**Can this workshop FAQ replace current Oracle deployment guidance?**

Use this small corpus to practice retrieval and cache correctness. For a real
service deployment, consult Oracle's documentation for the selected engine,
cluster mode, region, limits, and security requirements. The example answers
are teaching data and do not promise a service quota, availability target, or
compliance certification.
