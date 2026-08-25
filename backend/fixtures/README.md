# Fixtures

Test and seed data lives here. Per [CLAUDE.md](../../CLAUDE.md): never commit a real API key,
phone number, or any other PII into this directory. Use obviously-fake values (e.g.
`+15550100000` for numbers). Never paste anything in Hunar's or NVIDIA's live API key format
here, even as a "fake" example — CI's secret grep (`.github/workflows/ci.yml`) matches on the
literal key prefix alone, precisely so a fixture can't smuggle in something that merely looks
fake.
