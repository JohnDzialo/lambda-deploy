import argparse
#import base64
import os
import yaml
import zipfile
import boto3
import botocore


class Context(object):
    # Context object contains variables to be used during lambda deployment
    FUNCTION_NAME = ""      # FUNCTION_NAME: name of the lambda function to be created or updated
    RUNTIME = ""            # RUNTIME: runtime environment lambda will invoke function as (options: nodejs, java, python)
    DESCRIPTION = ""        # DESCRIPTION: short description of lambda function
    TIMEOUT = ""            # TIMEOUT: time in seconds before the function will timeout in (default: 3)
    MEMORY_SIZE = ""        # MEMORY_SIZE: how much memory in MB to allocate for lambda execution
    IAM_ROLE = ""           # IAM_ROLE: full ARN for the IAM role to be applied on lambda during creation or update
    HANDLER = ""            # HANDLE: function or module to be executed on invocation (default: index.handler)
    CODE = ""               # CODE: Dictionary to store bytes of the function zipfile
    ZIP_BYTES = ""          # ZIP_BYTES: bytes of the function zipfile
    ZIP_DIRECTORY = ""      # ZIP_DIRECTORY: directory to zip up (NOT IN USE YET)
    ENVIRONMENT = ""        # ENVIRONMENT: environment passed in through command line on each deploy (options: dev, stage, deploy, demo, prod)
    VERSION = ""            # VERSION: current lambda function version published at time of create or update
    OMIT_DIRS = ""          # OMIT_DIRS: directories to omit from the zip file
    OMIT_FILES = ""         # OMIT_FILES: files to omit from the zip file
    REGION = ""             # REGION: region where the lambda function exists

    def get_context_object(self):
        # Get context object from the yaml file and passed argument --env at runtime
        parser = argparse.ArgumentParser(description='Deploy Lambda Function to Specific Environment')
        parser.add_argument('--env', required=True, help='Environment to Deploy Lambda Function: dev, stage, prod')
        args = parser.parse_args()
        self.ENVIRONMENT = args.env
        config_file = file('bin/.lambda-deploy.yml', "r")
        config = yaml.load(config_file)
        self.FUNCTION_NAME = config['function_name']
        self.RUNTIME = config['runtime']
        self.DESCRIPTION = config['description']
        self.TIMEOUT = int(config['timeout'])
        self.MEMORY_SIZE = int(config['memory_size'])
        self.IAM_ROLE = config['iam_role']
        self.HANDLER = config['handler']
        self.OMIT_DIRS = config['omit_directories']
        self.OMIT_FILES = config['omit_files']
        self.REGION = config['region']
        return self


class Lambda(object):
    def __init__(self, region):
        # AWS Lambda class
        self.l = boto3.client('lambda', region)

    def check_lambda_function_exists(self, context):
        # Check if lambda function exists return True if it does, return False if it does not
        try:
            self.l.get_function(FunctionName=context.FUNCTION_NAME)
            print "Lambda Function %s exists" % context.FUNCTION_NAME
            return True
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print "Lambda Function %s does not exist" % context.FUNCTION_NAME
                return False
            else:
                print "Unexpected error in check_lambda_function_exists: %s" % e

    def check_lambda_function_alias_exists(self, context):
        # Check if lambda alias exists return True if it does, return False if it does not
        try:
            self.l.get_alias(FunctionName=context.FUNCTION_NAME, Name=context.ENVIRONMENT)
            print "Lambda Function %s has alias %s" % (context.FUNCTION_NAME, context.ENVIRONMENT)
            return True
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print "Lambda Function %s does not have alias %s" % (context.FUNCTION_NAME, context.ENVIRONMENT)
                return False
            else:
                print "Unexpected error in check_lambda_function_alias_exists: %s" % e

    def create_lambda_function(self, context):
        # Create lambda function with Publish=True to ensure a new version is published
        resp = self.l.create_function(FunctionName=context.FUNCTION_NAME,
                                      Runtime=context.RUNTIME,
                                      Role=context.IAM_ROLE,
                                      Handler=context.HANDLER,
                                      Code=context.CODE,
                                      Description=context.DESCRIPTION,
                                      MemorySize=context.MEMORY_SIZE,
                                      Timeout=context.TIMEOUT,
                                      Publish=True)
        return resp

    def update_lambda_function(self, context):
        # Update lambda function code with Publish=True to ensure a new version is published if code has changed
        resp = self.l.update_function_code(FunctionName=context.FUNCTION_NAME,
                                           ZipFile=context.ZIP_BYTES,
                                           Publish=True)
        return resp

    def update_lambda_function_configuration(self, context):
        # Update lambda function configuration based off of context variables
        resp = self.l.update_function_configuration(FunctionName=context.FUNCTION_NAME,
                                                    Role=context.IAM_ROLE,
                                                    Handler=context.HANDLER,
                                                    Description=context.DESCRIPTION,
                                                    Timeout=context.TIMEOUT,
                                                    MemorySize=context.MEMORY_SIZE)
        return resp

    def publish_lambda_version(self, context):
        # Publish a new lambda version for context.FUNCTION_NAME
        # NOT RECOMMENDED FOR USE:  Publish=True in create_function or update_function_code
        resp = self.l.publish_version(FunctionName=context.FUNCTION_NAME)
        return resp

    def list_lambda_function_version(self, context):
        # List lambda function versions by context.FUNCTION_NAME
        resp = self.l.list_versions_by_function(FunctionName=context.FUNCTION_NAME)
        return resp

    def list_lambda_function_aliases(self, context):
        # List lambda function aliases by context.FUNCTION_NAME
        resp = self.l.list_aliases(FunctionName=context.FUNCTION_NAME)
        return resp

    def list_lambda_function_aliases_by_version(self, context):
        # List lambda function aliases by context.FUNCTION_NAME and current context.VERSION
        resp = self.l.list_aliases(FunctionName=context.FUNCTION_NAME,
                                   FunctionVersion=context.VERSION)
        return resp

    def create_lambda_function_alias(self, context):
        # Create alias, context.ENVIRONMENT, for Lambda function, context.FUNCTION_NAME, for current context.VERSION
        resp = self.l.create_alias(FunctionName=context.FUNCTION_NAME,
                                   Name=context.ENVIRONMENT,
                                   FunctionVersion=context.VERSION)
        return resp

    def update_lambda_function_alias(self, context):
        # Update Lambda function, context.FUNCTION_NAME, with alias, context.ENVIRONMENT, for current context.VERSION
        resp = self.l.update_alias(FunctionName=context.FUNCTION_NAME,
                                   Name=context.ENVIRONMENT,
                                   FunctionVersion=context.VERSION)
        return resp

    def create_lambda_function_for_environment(self, context):
        # Create lambda function, version it and apply an alias of context.ENVIRONMENT
        print "Creating lambda function: %s" % context.FUNCTION_NAME
        resp = self.create_lambda_function(context)
        context.VERSION=resp['Version']
        update = self.check_lambda_function_alias_exists(context)
        if update is True:
            print "Updating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            self.update_lambda_function_alias(context)
        elif update is False:
            print "Creating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            self.create_lambda_function_alias(context)
        else:
            print "Error in check_lambda_function_alias_exists: %s %s" % (context.FUNCTION_NAME, context.ENVIRONMENT)

    def update_lambda_function_for_environment(self, context):
        # Update lambda function code, version it and apply an alias of context.ENVIRONMENT
        print "Updating lambda function: %s" % context.FUNCTION_NAME
        resp = self.update_lambda_function(context)
        self.update_lambda_function_configuration(context)
        print "Updated lambda version: %s" % resp['Version']
        context.VERSION = resp['Version']
        update = self.check_lambda_function_alias_exists(context)
        if update is True:
            print "Updating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            self.update_lambda_function_alias(context)
        elif update is False:
            print "Creating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            self.create_lambda_function_alias(context)
        else:
            print "Error in check_lambda_function_alias_exists: %s %s" % (context.FUNCTION_NAME, context.ENVIRONMENT)


def get_archive_encoded_bytes(archive):
    #  Open zip and read bytes to variable to pass to lambda code dictionary
    with open(archive, "rb") as f:
        zip_bytes = f.read()
    #  Base64 encoding no longer necessary as boto3 handles conversion
    #  Pass unencoded bytes
    # encoded = base64.b64encode(zip_bytes)
    return zip_bytes


def create_lambda_code_dictionary(encoded):
    #  Create dict for lambda code deployment
    code_dict = {}
    code_dict['ZipFile'] = encoded
    return code_dict


def zip_lambda_function(context):
    #  Create a zip file of the current project for lambda deployment
    archive = "bin/" + context.FUNCTION_NAME + ".zip"
    z = zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED)
    for dirname, subdirs, files in os.walk('.'):
        #  Omit directories and files specified in context from lists in-place
        subdirs[:] = list(filter(lambda x: not x in context.OMIT_DIRS, subdirs))
        files[:] = list(filter(lambda x: not x in context.OMIT_FILES, files))
        for filename in files:
            f = os.path.join(dirname, filename)
            print 'Zipping %s as %s' % (os.path.join(dirname, filename), archive)
            z.write(f)
    z.close()
    return archive


def parse_current_version_aliases(context, resp):
    #  Loop through all aliases of lambda function and match current version
    #  Add alias name to list if match
    aliases = []
    for a in resp['Aliases']:
        if a['FunctionVersion'] is context.VERSION:
            aliases.append(a['Name'])
            print "Parsed aliases: %s" % aliases
    return aliases


def main():
    context = Context().get_context_object()
    l = Lambda(context.REGION)

    archive = zip_lambda_function(context)
    encoded = get_archive_encoded_bytes(archive)
    check = l.check_lambda_function_exists(context)
    context.ZIP_BYTES = encoded
    context.CODE = create_lambda_code_dictionary(encoded)

    if check is True:
        l.update_lambda_function_for_environment(context)
    elif check is False:
        l.create_lambda_function_for_environment(context)
    else:
        print "Unknown Error in check_lambda_function_exists"
        exit()

if __name__ == '__main__':
    main()
