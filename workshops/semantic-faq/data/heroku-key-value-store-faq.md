# Heroku Key-Value Store FAQs

## What is Heroku Key-Value Store and is it compatible with Redis®?

Heroku Key-Value Store is a fully managed, secure, and scalable key-value datastore built on the open-source Valkey project. Yes, it maintains high compatibility with Redis® OSS, allowing you to use standard Redis® clients, tools, and drivers without modifying your application code.

Because of its low-latency performance, it is ideal for high-speed use cases. Beyond sub-millisecond caching, it powers high-throughput ephemeral workloads including session storage, real-time leaderboards, and message queuing. Check out our Key-Value Store documentation in the Heroku Dev Center to learn more.

## How does Heroku ensure high availability for my key-value store?

Heroku ensures key-value store resilience through Premium, Private, and Shield plans. These plans automatically provision a standby replica in a separate availability zone. In the event of a primary instance failure, the service automatically fails over to the standby, ensuring your application remains online with minimal disruption.

## Is Heroku Key-Value Store suitable for applications handling sensitive data like PII or PHI?

Yes, Heroku Shield Key-Value Store provides a HIPAA-compliant environment for processing sensitive data (PII/PHI). These plans enforce strict security controls, including network isolation within a Shield Private Space, encrypted backups, and encryption-in-transit, making them ideal for healthcare, finance, and other regulated industries.

## What advanced data modules are available in Heroku Key-Value Store?

Heroku Key-Value Store supports powerful modules to extend functionality beyond simple caching. Available modules include Valkey Bloom for probabilistic data structures (like bloom filters), and ValkeyJSON for storing, updating, and querying complex JSON data natively. These modules allow you to build sophisticated and efficient data-intensive features directly within your key-value store.

## How can I monitor the performance of my Key-Value Store instance?

You can monitor your Heroku Key-Value Store instance using Performance Analytics, a visual dashboard in the Heroku CLI and Dashboard that tracks critical runtime metrics like active connections, memory usage, and throughput. Additionally, you can inspect real-time logs to identify slow operations or bandwidth spikes, and integrate with third-party monitoring add-ons for advanced alerting.

## Can I use my own encryption keys with Heroku Key-Value Store?

Yes, Heroku Private Key-Value Store and Shield Key-Value Store plans support Bring Your Own Key (BYOK) encryption. This allows you to manage the encryption keys for your data at rest using your own AWS Key Management Service (KMS) account, giving you full custody over key lifecycle and access revocation.

## How do I connect Heroku Key-Value Store to resources in AWS?

You can securely connect your Heroku Key-Value Store to external AWS resources (like EC2 or Lambda) using PrivateLink. Available on Private and Shield plans, this feature creates a secure, unidirectional connection that keeps traffic entirely within the AWS private network, bypassing the public internet for enhanced security and lower latency.

## Can I use Heroku Key-Value Store for session management?

Yes. Heroku Key-Value Store is an industry-standard solution for session management due to its sub-millisecond latency. By storing user session data in-memory, you ensure fast page loads and a seamless user experience for high-traffic web applications.
