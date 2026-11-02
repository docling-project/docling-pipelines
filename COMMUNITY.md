# Community Guidelines

This document covers community guidelines, support channels, response time expectations, and maintainer responsibilities for `docling-pipelines`.

---

## Table of Contents

- [Community Guidelines](#community-guidelines-1)
- [Support Channels](#support-channels)
- [Response Time Expectations](#response-time-expectations)
- [Maintainer Responsibilities](#maintainer-responsibilities)
- [Maintainers](#maintainers)

---

## Community Guidelines

`docling-pipelines` is an open-source project. We welcome contributions, questions, and feedback from everyone. To keep the community healthy and productive, all participants are expected to follow these guidelines.

### Be Respectful

- Treat everyone with respect, regardless of experience level, background, or opinions.
- Use welcoming and inclusive language.
- Assume good intent — if something seems rude, consider that it may be a language or cultural difference.

### Be Constructive

- Provide actionable, specific feedback when reviewing code or issues.
- When disagreeing, explain your reasoning clearly.
- Focus on improving the project, not winning arguments.

### Be Collaborative

- Share knowledge openly. If you figure something out, document it or open a discussion so others benefit.
- Coordinate on large changes before investing significant time — open an issue to discuss the approach first.
- Credit contributors fairly in commit messages, release notes, and documentation.

### Scope

- Keep discussions on-topic for `docling-pipelines`. Off-topic content may be removed.
- Bug reports, feature requests, and questions belong in [GitHub Issues](https://github.com/docling-project/docling-pipelines/issues) or [GitHub Discussions](https://github.com/docling-project/docling-pipelines/discussions).

### Enforcement

Violations of these guidelines may result in comments being removed or contributors being temporarily or permanently blocked. Severe or repeated violations will be escalated to IBM's open source governance process.

To report a conduct issue, email the maintainers at the addresses listed in the [Maintainers](#maintainers) section.

---

## Support Channels

| Channel | Purpose | Link |
|---------|---------|------|
| **GitHub Issues** | Bug reports, feature requests, operator questions | [github.com/docling-project/docling-pipelines/issues](https://github.com/docling-project/docling-pipelines/issues) |
| **GitHub Discussions** | General questions, ideas, show & tell, Q&A | [github.com/docling-project/docling-pipelines/discussions](https://github.com/docling-project/docling-pipelines/discussions) |
| **Pull Requests** | Code contributions, documentation improvements | [github.com/docling-project/docling-pipelines/pulls](https://github.com/docling-project/docling-pipelines/pulls) |
| **Security vulnerabilities** | Private disclosure of security issues | See [SECURITY.md](.github/SECURITY.md) |

### When to use which channel

- **Something is broken** → Open a [GitHub Issue](https://github.com/docling-project/docling-pipelines/issues/new) using the bug report template.
- **I have a feature idea** → Open a [GitHub Issue](https://github.com/docling-project/docling-pipelines/issues/new) using the feature request template.
- **I have a question about usage** → Start a [GitHub Discussion](https://github.com/docling-project/docling-pipelines/discussions/new?category=q-a) in the Q&A category.
- **I want to contribute** → Read [CONTRIBUTING.md](CONTRIBUTING.md) and open a PR.
- **I found a security vulnerability** → Follow the process in [SECURITY.md](.github/SECURITY.md). Do **not** open a public issue.

### Out-of-scope support

The maintainers cannot provide support for:

- IBM internal infrastructure or credentials issues
- Forked or modified versions of `docling-pipelines`
- Third-party integrations not documented in this repository

---

## Response Time Expectations

These are best-effort targets. The maintainers are a small team — your patience is appreciated.

| Activity | Target response time | Notes |
|----------|---------------------|-------|
| New bug report | 5 business days | Initial triage and label assignment |
| Security vulnerability | 2 business days | Initial acknowledgement; see [SECURITY.md](.github/SECURITY.md) |
| Feature request | 10 business days | Initial triage; may be deferred to backlog |
| Pull request (first review) | 10 business days | Complex PRs may take longer |
| Pull request (subsequent reviews) | 5 business days | After author addresses feedback |
| General question (Discussions) | 10 business days | Community members are welcome to answer too |

### Notes

- Response times may be longer during IBM public holidays.
- Issues labelled `good first issue` are actively monitored and prioritised for community engagement.
- Critical security issues are handled with the highest priority regardless of the targets above.
- If you have not received a response within the target window, please add a comment to the issue to prompt a re-triage.

---

## Maintainer Responsibilities

Maintainers are trusted contributors with write access to the repository. Their responsibilities are:

### Issue Triage

- Review new issues within the response time targets above.
- Apply appropriate labels (`bug`, `enhancement`, `documentation`, `good first issue`, etc.).
- Assign issues to milestones where appropriate.
- Close duplicate, out-of-scope, or invalid issues with a clear explanation.

### Pull Request Review

- Review PRs in a timely manner (see targets above).
- Provide specific, actionable feedback.
- Approve and merge PRs that meet the project standards defined in [CONTRIBUTING.md](CONTRIBUTING.md).
- Ensure CI checks pass before merging.
- Squash-merge or rebase as appropriate to keep a clean commit history.

### Release Management

- Follow the [Release Process](RELEASE_PROCESS.md) for every release.
- Keep [CHANGELOG.md](CHANGELOG.md) up to date.
- Publish release notes and announcements per the [Release Announcement Plan](RELEASE_PROCESS.md#release-announcement-plan).
- Tag releases with signed git tags.

### Security

- Monitor Dependabot and Mend/Whitesource alerts and act on critical/high severity findings within 10 business days.
- Handle privately-reported vulnerabilities per [SECURITY.md](.github/SECURITY.md).
- Rotate any compromised credentials immediately.

### Community Health

- Enforce the community guidelines in this document fairly and consistently.
- Welcome new contributors and direct them to `good first issue` labels.
- Maintain documentation accuracy — update docs when code changes.
- Participate in GitHub Discussions to help the community.

### Becoming a Maintainer

Consistent contributors who have demonstrated code quality, reliability, and alignment with project values may be invited to become maintainers. The current maintainers make this decision by consensus. There is no formal application process — sustained, high-quality contribution is the path.

---

## Maintainers

The full list of maintainers is in [MAINTAINERS.md](MAINTAINERS.md).

**Point of contact:** [docling_pipeline_team-dg@ibm.com](mailto:docling_pipeline_team-dg@ibm.com)

For private matters (security issues, conduct reports), open a private security advisory via [GitHub Security Advisories](https://github.com/docling-project/docling-pipelines/security/advisories/new) or email the team directly at [docling_pipeline_team-dg@ibm.com](mailto:docling_pipeline_team-dg@ibm.com).
