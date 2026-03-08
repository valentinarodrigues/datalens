# DataLens — Lambda container image
#
# Uses AWS's official Lambda Python base image so the runtime, extensions,
# and Lambda RIC (Runtime Interface Client) are pre-installed.
#
# Build:  docker build -t datalens-backend .
# Local test via Lambda RIE:
#   docker run -p 9000:8080 datalens-backend
#   curl -X POST http://localhost:9000/2015-03-31/functions/function/invocations \
#     -d '{"version":"2.0","routeKey":"GET /health","rawPath":"/health","headers":{},"requestContext":{"http":{"method":"GET"}},"isBase64Encoded":false}'

FROM public.ecr.aws/lambda/python:3.11

# Install dependencies into the Lambda task root so they're on the module path.
# Use --no-cache-dir to keep the image lean.
COPY requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy application source
COPY . ${LAMBDA_TASK_ROOT}/

# Lambda handler: file `main.py`, object `handler` (the Mangum wrapper)
CMD ["main.handler"]
