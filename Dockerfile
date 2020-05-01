FROM python:3

RUN mkdir -p /var/app
WORKDIR /var/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bitbucket_issues_to_github.py .

ARG token
ENV GITHUB_ACCESS_TOKEN=$token

ARG file_name
CMD python ./bitbucket_issues_to_github.py $file_name