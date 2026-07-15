# Security Policy

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it privately:

- **Email**: caihu0916@126.com
- **Subject**: [Security] TaskForge Vulnerability Report

Please **do not** file a public GitHub issue for security vulnerabilities.

## What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

## Response Timeline

- **Acknowledgment**: Within 24 hours
- **Initial Assessment**: Within 72 hours
- **Fix Timeline**: Critical issues within 7 days, others within 30 days

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Active development |

## Security Features

- JWT-based authentication with 60-minute expiry
- Rate limiting (20 req/min per IP)
- Account lockout after 5 failed login attempts (15-minute cooldown)
- Ed25519 package signing for closed-source extensions
- No hardcoded secrets in source code
- All sensitive data encrypted at rest using SecureStorage

## Known Security Considerations

- This is the **open-source edition** — billing, connectors, and advanced security features are in the closed-source Pro package
- Local LLM mode (Ollama) does not transmit data externally
- Remote LLM mode sends prompts to configured API endpoints
