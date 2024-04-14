from wagtail.core.models import Collection, Site, Task, Workflow
from wagtail.core.permission_policies import ModelPermissionPolicy
from wagtail.core.permission_policies.collections import CollectionMangementPermissionPolicy


site_permission_policy = ModelPermissionPolicy(Site)
task_permission_policy = ModelPermissionPolicy(Task)
workflow_permission_policy = ModelPermissionPolicy(Workflow)
collection_permission_policy = CollectionMangementPermissionPolicy(Collection)
