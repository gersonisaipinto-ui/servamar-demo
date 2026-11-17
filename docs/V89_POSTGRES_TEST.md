# SERVAMAR V89 — PostgreSQL TEST environment

The Neon test branch is `servamar-v89-pruebas-postgresql` (`br-green-band-arsmtoxc`), database `servamar_demo`, schema `servamar_test`.

**Isolated test data only:** 3 fictional vessels and 9 alert settings. The production SQLite application is unchanged.

To launch the standalone testing console (do **not** deploy over the existing Render service):

1. Create a separate private Render Web Service using this repository.
2. Start command: `gunicorn postgres_test_app:app --bind 0.0.0.0:$PORT`.
3. Set private environment variables:
   - `SERVAMAR_PG_TEST_MODE=YES`
   - `SERVAMAR_PG_TEST_BRANCH_ID=br-green-band-arsmtoxc`
   - `SERVAMAR_PG_TEST_USERNAME=servamar-test`
   - `SERVAMAR_PG_TEST_PASSWORD=<unique password of at least 16 characters>`
   - `SERVAMAR_PG_TEST_DATABASE_URL=<Neon connection string for the TEST branch only>`
4. Open the separate service URL over HTTPS. The UI requires HTTP Basic authentication.
5. Create records only with declarations starting `ST-TEST-` or `ST-DEMO-`.

The standalone app has no email/push integrations. It supports listing vessels, adding fictional vessels, listing alerts, listing and adding movements through its JSON API.

**Important:** This is not a production migration, and there is no public test URL until a separate service is deployed. The branch guard environment variable is a configuration safety check, not a cryptographic guarantee of the connection target. Never paste credentials into the GitHub repository.
