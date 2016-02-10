import argparse
#import base64
import os
import yaml
import zipfile
import boto3
import botocore


class Context(object):
    FUNCTION_NAME = ""
    RUNTIME = ""
    DESCRIPTION = ""
    TIMEOUT = ""
    MEMORY_SIZE = ""
    IAM_ROLE = ""
    HANDLER = ""
    CODE = ""
    ZIP_BYTES = ""
    ENVIRONMENT = ""
    VERSION = ""
    OMIT_DIRS = ""
    OMIT_FILES = ""
    REGION = ""

    def get_context_object(self):
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
        self.l = boto3.client('lambda', region)

    def check_lambda_function_exists(self, context):
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
        resp = self.l.update_function_code(FunctionName=context.FUNCTION_NAME,
                                           ZipFile=context.ZIP_BYTES,
                                           Publish=True)
        return resp

    def update_lambda_function_configuration(self, context):
        resp = self.l.update_function_configuration(FunctionName=context.FUNCTION_NAME,
                                                    Role=context.IAM_ROLE,
                                                    Handler=context.HANDLER,
                                                    Description=context.DESCRIPTION,
                                                    Timeout=context.TIMEOUT,
                                                    MemorySize=context.MEMORY_SIZE)
        return resp

    def publish_lambda_version(self, context):
        resp = self.l.publish_version(FunctionName=context.FUNCTION_NAME)
        return resp

    def list_lambda_function_version(self, context):
        resp = self.l.list_versions_by_function(FunctionName=context.FUNCTION_NAME)
        return resp

    def list_lambda_function_aliases(self, context):
        resp = self.l.list_aliases(FunctionName=context.FUNCTION_NAME)
        return resp

    def list_lambda_function_aliases_by_version(self, context):
        resp = self.l.list_aliases(FunctionName=context.FUNCTION_NAME,
                                   FunctionVersion=context.VERSION)
        return resp

    def create_lambda_function_alias(self, context):
        resp = self.l.create_alias(FunctionName=context.FUNCTION_NAME,
                                   Name=context.ENVIRONMENT,
                                   FunctionVersion=context.VERSION)
        return resp

    def update_lambda_function_alias(self, context):
        resp = self.l.update_alias(FunctionName=context.FUNCTION_NAME,
                                   Name=context.ENVIRONMENT,
                                   FunctionVersion=context.VERSION)
        return resp


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
    archive = context.FUNCTION_NAME + ".zip"
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
    env = context.ENVIRONMENT

    if check is True and env == 'dev':
        print "Updating lambda function:  %s in %s" % (context.FUNCTION_NAME, env)
        context.ZIP_BYTES = encoded
        resp = l.update_lambda_function(context)
        l.update_lambda_function_configuration(context)
        print "Updated lambda version: %s" % resp['Version']
        context.VERSION = resp['Version']
        resp = l.list_lambda_function_aliases(context)
        aliases = parse_current_version_aliases(context, resp)
        for a in aliases:
            if a in ['dev', 'stage', 'prod']:
                print "Version %s is already being used" % context.VERSION
                print "There is a problem.  Exiting!"
                exit()
        update = l.check_lambda_function_alias_exists(context)
        if update is True:
            print "Updating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            l.update_lambda_function_alias(context)
        elif update is False:
            print "Creating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            l.create_lambda_function_alias(context)
        else:
            print "Error in check_lambda_function_alias_exists: %s %s" % (context.FUNCTION_NAME, context.ENVIRONMENT)

    elif check is True and env == 'stage':
        print "Updating lambda function:  %s in %s" % (context.FUNCTION_NAME, env)
        context.ZIP_BYTES = encoded
        resp = l.update_lambda_function(context)
        l.update_lambda_function_configuration(context)
        print "Updated lambda version: %s" % resp['Version']
        context.VERSION = resp['Version']
        resp = l.list_lambda_function_aliases(context)
        aliases = parse_current_version_aliases(context, resp)
        for a in aliases:
            if a in ['stage', 'prod']:
                print "Version %s is already being used" % context.VERSION
                print "There is a problem.  Exiting!"
                exit()
        update = l.check_lambda_function_alias_exists(context)
        if update is True:
            print "Updating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            l.update_lambda_function_alias(context)
        elif update is False:
            print "Creating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            l.create_lambda_function_alias(context)
        else:
            print "Error in check_lambda_function_alias_exists: %s %s" % (context.FUNCTION_NAME, context.ENVIRONMENT)

    elif check is True and env == 'prod':
        print "Updating lambda function:  %s in %s" % (context.FUNCTION_NAME, env)
        context.ZIP_BYTES = encoded
        resp = l.update_lambda_function(context)
        l.update_lambda_function_configuration(context)
        print "Updated lambda version: %s" % resp['Version']
        context.VERSION = resp['Version']
        resp = l.list_lambda_function_aliases(context)
        aliases = parse_current_version_aliases(context, resp)
        for a in aliases:
            if a in ['prod']:
                print "Version %s is already being used" % context.VERSION
                print "There is a problem.  Exiting!"
                exit()
        update = l.check_lambda_function_alias_exists(context)
        if update is True:
            print "Updating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            l.update_lambda_function_alias(context)
        elif update is False:
            print "Creating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            l.create_lambda_function_alias(context)
        else:
            print "Error in check_lambda_function_alias_exists: %s %s" % (context.FUNCTION_NAME, context.ENVIRONMENT)

    elif check is False and env == 'dev':
        print "Creating lambda function: %s" % context.FUNCTION_NAME
        context.CODE = create_lambda_code_dictionary(encoded)
        l.create_lambda_function(context)
        update = l.check_lambda_function_alias_exists(context)
        if update is True:
            print "Updating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            l.update_lambda_function_alias(context)
        elif update is False:
            print "Creating alias %s for function %s" % (context.ENVIRONMENT, context.FUNCTION_NAME)
            l.create_lambda_function_alias(context)
        else:
            print "Error in check_lambda_function_alias_exists: %s %s" % (context.FUNCTION_NAME, context.ENVIRONMENT)
    else:
        print "Unknown Error in check_lambda_function_exists"
        exit()

if __name__ == '__main__':
    main()