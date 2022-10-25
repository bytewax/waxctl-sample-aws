# Wax on Wax off - AWS flavor

We will eventually get to the tutorial on getting your dataflow production ready and deploying your dataflow to AWS with GitHub Actions, but first, a bit about why we built Waxctl, and what it is.

Waxctl is the Bytewax command line interface that simplifies deployment and management of Bytewax dataflows. We built Waxctl to provide an interface that would mirror the experience that cloud or serverless platforms provide, but with your resources and your data staying within your network. We are still early on this vision, but it is core to the mission of Bytewax, which is to simplify development on streaming data. The decision to build a peripheral tool set around the core open source project instead of building a hosted version was a particularly important decision for us since we wanted our users to have complete control and feel at ease while running workflows that process sensitive data. With today’s virtualization technology, IaaS options and DevOps tooling, it's possible to build a user experience where you can focus on writing the code that matters (your dataflows) and not on how to configure instances and integrate with a myriad of devops tools. If you still want a more managed service where everything is managed, please [contact us](sales@bytewax.io). Let’s get on with how to use Waxctl!

So you have written an awesome dataflow. Something that is revolutionary and now you need to run it on something that is not your laptop :). Waxctl is here to help. In this post, we are going to walk you through how you can turn your local dataflow into something ready for production with test and that can be automatically deployed to one of the public clouds. This is meant for smaller deployments that are not using Kubernetes, if you are using Kubernetes, please check out our documentation on how to use [Waxctl with Kubernetes](https://www.bytewax.io/docs/deployment/waxctl).

For the purposes of this tutorial, we are going to build upon some code from a prior blog post that streams events from wikimedia SSE stream. The code referenced in the rest of the post can be found in the [waxctl-aws Repository](https://github.com/bytewax/waxctl-sample-aws)

## Writing and Running some tests

Working within the context of a data stream can be difficult because the data is always changing, it is helpful to take a sample of your data and use that when you are developing locally and testing the dataflow. To modify an existing dataflow to use a test set of data we will add/modify the following lines.

```diff
# dataflow.py
from bytewax.recovery import SqliteRecoveryConfig
from bytewax.window import SystemClockConfig, TumblingWindowConfig

+ ENVIRONMENT = os.getenv("ENVIRONMENT", None)
…
…
flow = Dataflow()
- flow.input("inp", ManualInputConfig(input_builder))
+ if ENVIRONMENT in ["TEST", "DEV"]:
+     with open("test_data.txt") as f:
+         inp = f.read().splitlines()
+     flow.input("inp", TestingInputConfig(inp))
+ else:
+     flow.input("inp", ManualInputConfig(input_builder))
flow.map(json.loads)
flow.map(initial_count)
```

Now when we run our code the `TEST` or `DEV` set as the environment variable named `Environment` we will use our test_data as input instead of consuming from the SSE stream. This will make it easier to work on code changes locally, and we can go one step further with this and write some tests that will run with pytest. :ninja:

Let’s take a peak at how we can run our dataflow as a test. 

```python
from dataflow import flow
from bytewax.execution import run_main
from bytewax.outputs import TestingOutputConfig


def test_dataflow():
    out = []
    flow.capture(TestingOutputConfig(out))
    run_main(flow)
    data = [
            ('commons.wikimedia.org', 1),
            ('ca.wikipedia.org', 1),
            ('species.wikimedia.org', 1),
            ('en.wikipedia.org', 2),
            ('ar.wikipedia.org', 1),
            ('fr.wikipedia.org', 1),
            ('id.wikipedia.org', 9),
            ('www.wikidata.org', 15),
            ('ro.wikipedia.org', 1),
        ]
    assert sorted(out) == sorted(data)
```

With very little additional code, we were able to add a test that we can run on each code change to ensure the dataflow is still running correctly. For the additions we made to our dataflow and our new test file, we are leveraging the `TestingInputConfig` and `TestOutputConfig` helpers.

Now that we have our code running locally, let’s look at how we can setup some GitHub Action Workflows to test our code. This will ensure that our code won’t break with any additional changes. To add an Actions workflow, we will add a new YAML file in the `.github/workflows/` directory with the following code.

```yaml
name: Python Tests

on: [push]

jobs:
  build:

    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10"]

    steps:
      - uses: actions/checkout@v3
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install flake8 pytest
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - name: Lint with flake8
        run: |
          # stop the build if there are Python syntax errors or undefined names
          flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
          # exit-zero treats all errors as warnings. The GitHub editor is 127 chars wide
          flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
      - name: Test with pytest
        run: |
          # add our TEST env var
          ENVIRONMENT=TEST pytest
```

This will test our dataflow with each new code change! Nice!

Next let’s look at how we can package our dataflow and run it on AWS EC2.

## Automating Build and Deployment

We will use waxctl to get started here. Waxctl allows you to easily deploy and manage dataflows on kubernetes or on public cloud virtual machines like AWS EC2. For more details on waxctl, you can check out the long format [docs on waxctl](https://www.bytewax.io/docs/deployment)

If you use the Homebrew package manager you can install it with brew install waxctl. Otherwise, you can find the right installation binary on the [bytewax website](https://www.bytewax.io/downloads). Once completed, you can start managing your dataflows with Bytewax. 

Since we are looking to automate this process after our tests pass. We are going to use GitHub actions again and Waxctl to deploy our dataflow.

To do so, we will do the following:

1. Create the correct security credentials in AWS
2. Set those credentials as secrets in our GitHub repository
3. Write a workflow that will use Waxctl to deploy our dataflow
4. Use Waxctl locally to check the status of our Dataflow

### AWS Security Credentials

First we will need to create an iam user and then attach a narrow policy to that user before creating the access credentials.

```
aws iam create-user --user-name bytewax-actions
```

Create a policy for the user 

```
cat << EOF > bytewax-policy.json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": "ec2:*",
            "Resource": "*",
            "Effect": "Allow",
            "Condition": {
                "StringEquals": {
                    "ec2:Region": "us-east-2"
                }
            }
        }
    ]
}
EOF
```

Now we can attach the policy

```
aws iam create-policy --policy-name Bytewax --policy-document file://bytewax-policy.json
```

With the policy created, we will attach it to the user we created

```
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
aws iam attach-user-policy --policy-arn arn:aws:iam::$AWS_ACCOUNT_ID:policy/Bytewax --user-name bytewax-actions
```

With that done, we can create a aws secret access key and aws access key id:

```
aws iam create-access-key --user-name bytewax-actions | jq -r .AccessKey.SecretAccessKey
aws iam list-access-keys --user-name bytewax-actions --query "AccessKeyMetadata[0].AccessKeyId" --output text
```

And set those as secrets in our GitHub repository.

<img width="1596" alt="Screen Shot 2022-10-24 at 4 46 49 PM" src="https://user-images.githubusercontent.com/6073079/197626227-a21b5230-dfca-43f1-a201-1f83a9c7b77b.png">


Now we have what we need to configure a deployment workflow that will run when a PR is closed and new code is merged into main. 

```
jobs:
  deploy:
    name: Deploy to EC2
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
    - name: Checkout
      uses: actions/checkout@v2

    - name: Configure AWS credentials
      uses: aws-actions/configure-aws-credentials@v1
      with:
        aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
        aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        aws-region: us-east-2

    - name: Install waxctl
      run: |
        eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
        brew tap bytewax/tap
        brew install waxctl

    - name: Waxctl Deploy
      run: |
        waxctl aws deploy dataflow.py \
        --name wikievents \
        --requirements-file-name requirements.txt
```

Walking through the workflow above, what we have done is setup the aws cli with our credentials for the bytewax user and then we have installed waxctl and used it to deploy our workflow. There are many other configurations for things like the type of the instance, security groups, and other advanced configurations. You can see the full list in the [documentation](https://www.bytewax.io/docs/deployment/waxctl-aws#available-aws-sub-commands)

## Monitoring

If you have cloudwatch enabled, you will automatically get access to the logs and metrics associated. To access the cloudwatch details of the dataflow we just started, run the following command:

```
waxctl aws ls --verbose
```

Scrolling down to the “logs” section you will find a URL. You need to be authenticated in your AWS management console, but once you are, you can simply click the link and see the cloudwatch logs for your instance.

```
"logs": "https://us-east-2.console.aws.amazon.com/cloudwatch/home?region=us-east-2#logsV2:log-groups/log-group/$252Fbytewax$252Fsyslog/log-events/wikievents$3FfilterPattern$3Dbytewax"
```

By clicking the link in your terminal or copying and pasting the URL in your browser, we can see the logs for our dataflow running in EC2.

<img width="1778" alt="Screen Shot 2022-10-24 at 4 44 24 PM" src="https://user-images.githubusercontent.com/6073079/197625682-a8031ae3-c95a-4dc9-8741-c07ae8f1a004.png">


That’s it, you are now running a dataflow on EC2! Congratulations.

Give us a [star](https://github.com/bytewax/bytewax) if you liked this content.
