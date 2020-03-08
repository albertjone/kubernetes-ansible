#!/usr/bin/env python
#
# Copyright 2020 Caoyingjun
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

DOCUMENTATION = '''
author: Caoyingjun

'''

import abc
import six
import subprocess
import traceback


master_images = ['kube-apiserver',
                 'kube-controller-manager',
                 'kube-scheduler',
                 'etcd',
                 'coredns',
                 'kube-proxy',
                 'pause']
node_images = ['coredns', 'kube-proxy', 'pause']


@six.add_metaclass(abc.ABCMeta)
class RuntimeBase(object):

    def __init__(self, params):
        self.params = params
        self.image = self.params.get('image')
        self.image_repository = self.params.get('image_repository')
        self.kubernetes_version = self.params.get('kubernetes_version')

        self.changed = False
        self.result = {}

    def run_cmd(self, cmd):
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                shell=True)
        stdout, stderr = proc.communicate()
        retcode = proc.poll()
        if retcode != 0:
            output = 'stdout: "%s", stderr: "%s"' % (stdout, stderr)
            raise subprocess.CalledProcessError(retcode, cmd, output)
        return stdout.rstrip()

    def get_kube_images(self):
        # Get the images which kubernetes need for seting up cluster
        kube_cmd = ('kubeadm config images list '
                    '--image-repository {repository} '
                    '--kubernetes-version {version}'.format(
                        repository=self.image_repository,
                        version=self.kubernetes_version))

        return self.run_cmd(kube_cmd)

    def get_image(self):
        kube_images = self.get_kube_images()
        images_list = []
        for image in kube_images.split():
            image_repo, image_tag = image.split(':')
            image_name = image_repo.split('/')[-1]
            if image_name in master_images:
                images_list.append({'image_repo': image_repo,
                                    'image_tag': image_tag,
                                    'group': 'kube-master'})
            if image_name in node_images:
                images_list.append({'image_repo': image_repo,
                                    'image_tag': image_tag,
                                    'group': 'kube-node'})
        self.result['images_list'] = images_list

    @abc.abstractmethod
    def pull_image(self):
        pass

    @abc.abstractmethod
    def get_local_images(self):
        pass


class DockerRuntime(RuntimeBase):

    def __init__(self, params):
        super(DockerRuntime, self).__init__(params)

    def pull_image(self):
        # NOTE(caoyingjun): Pull the image from aliyun or private repo.
        # image's format is REPOSITORY:TAG
        local_images = self.get_local_images()
        if self.image not in local_images:
            self.run_cmd('docker pull {image}'.format(image=self.image))
            self.changed = True

    def get_local_images(self):
        images = self.run_cmd('docker images')
        images = images.split('\n')[1:]
        return [':'.join(image.split()[:2])
                for image in images]


class ContainerdRuntime(RuntimeBase):

    def __init__(self, params):
        super(ContainerdRuntime, self).__init__(params)

    def pull_image(self):
        local_images = self.get_local_images()
        if self.image not in local_images:
            self.run_cmd('ctr -n k8s.io images pull {image}'.format(image=self.image))
            self.changed = True

    def get_local_images(self):
        images = self.run_cmd('ctr -n k8s.io images list')
        images = images.split('\n')[1:]
        return [image.split()[0] for image in images]


def main():

    specs = dict(
        image=dict(type='str', default=''),
        image_repository=dict(type='str', required=True),
        kubernetes_version=dict(type='str', required=True),
        runtime_action=dict(type='str', default='pull'),
        runtime_type=dict(type='str'),
    )
    module = AnsibleModule(argument_spec=specs, bypass_checks=True)  # noqa
    params = module.params

    RUNTIMES = {
        'docker': DockerRuntime,
        'containerd': ContainerdRuntime
    }

    rc = None
    try:
        runtime_type = params.get('runtime_type')
        if runtime_type not in RUNTIMES:
            raise Exception('Unsuppported containerd runtime: {runtime_type}'.format(
                runtime_type=runtime_type))

        rc = RUNTIMES[runtime_type](params)
        getattr(rc, '_'.join([params.get('runtime_action'), 'image']))()
        module.exit_json(changed=rc.changed, result=rc.result)
    except Exception:
        module.fail_json(changed=True, msg=repr(traceback.format_exc()),
                         failed=True)


# import module snippets
from ansible.module_utils.basic import *  # noqa
if __name__ == '__main__':
    main()