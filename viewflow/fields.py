from __future__ import unicode_literals

from django.db import models
from .compat import get_app_package, get_containing_app_data, import_string
from .exceptions import FlowRuntimeError
from .token import Token


def import_flow_by_ref(flow_strref):
    app_label, flow_path = flow_strref.split('/')
    return import_string('{}.{}'.format(get_app_package(app_label), flow_path))


def get_flow_ref(flow_cls):
    module = "{}.{}".format(flow_cls.__module__, flow_cls.__name__)
    app_label, app_package = get_containing_app_data(module)
    if app_label is None:
        raise FlowRuntimeError('No application found for {}. Check your INSTALLED_APPS setting'.format(module))

    subpath = module[len(app_package)+1:]
    return "{}/{}".format(app_label, subpath)


def import_task_by_ref(task_strref):
    """
    Return flow task by reference like `app_label/path.to.Flowcls.task_name`
    """
    app_label, flow_path = task_strref.split('/')
    flow_path, task_name = flow_path.rsplit('.', 1)
    flow_cls = import_string('{}.{}'.format(get_app_package(app_label), flow_path))
    return flow_cls._meta.node(task_name)


def get_task_ref(flow_task):
    module = flow_task.flow_cls.__module__
    app_label, app_package = get_containing_app_data(module)
    if app_label is None:
        raise FlowRuntimeError('No application found for {}. Check your INSTALLED_APPS setting'.format(module))

    subpath = module[len(app_package)+1:]

    return "{}/{}.{}.{}".format(app_label, subpath, flow_task.flow_cls.__name__, flow_task.name)


class ClassValueWrapper(object):
    """
    Wrapper to get around of passing cls objects callable to django
    queryset
    """
    def __init__(self, cls):
        self.cls = cls


class _SubfieldBase(type):
    """backpoort from django 1.8"""
    def __new__(cls, name, bases, attrs):
        new_class = super(_SubfieldBase, cls).__new__(cls, name, bases, attrs)
        new_class.contribute_to_class = _make_contrib(
            new_class, attrs.get('contribute_to_class')
        )
        return new_class


class _Creator(object):
    """backpoort from django 1.8"""
    def __init__(self, field):
        self.field = field

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        return obj.__dict__[self.field.name]

    def __set__(self, obj, value):
        obj.__dict__[self.field.name] = self.field.to_python(value)


def _make_contrib(superclass, func=None):
    """backport from django 1.8"""
    def contribute_to_class(self, cls, name, **kwargs):
        if func:
            func(self, cls, name, **kwargs)
        else:
            super(superclass, self).contribute_to_class(cls, name, **kwargs)
        setattr(cls, self.name, _Creator(self))
    return contribute_to_class


class FlowReferenceField(models.CharField, metaclass=_SubfieldBase):
    description = """Flow class reference field,
    stores flow as app_label/flows.FlowName> to
    avoid possible collisions with app name changes"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 250)
        super(FlowReferenceField, self).__init__(*args, **kwargs)

    def to_python(self, value):
        if isinstance(value, str) and value:
            return import_flow_by_ref(value)
        return value

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        elif isinstance(value, str):
            return value
        elif isinstance(value, ClassValueWrapper):
            value = value.cls
        elif not isinstance(value, type):
            # HACK: Django calls callable due query parameter
            # preparation. So here we can get Flow instance,
            # even if we pass Flow class to query.
            value = value.__class__

        return get_flow_ref(value)

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return self.get_prep_value(value)


class TaskReferenceField(models.CharField, metaclass=_SubfieldBase):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 150)
        super(TaskReferenceField, self).__init__(*args, **kwargs)

    def to_python(self, value):
        if isinstance(value, str) and value:
            return import_task_by_ref(value)
        return value

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        elif not isinstance(value, str):
            return get_task_ref(value)
        return value

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return self.get_prep_value(value)


class TokenField(models.CharField, metaclass=_SubfieldBase):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 150)
        if 'default' in kwargs:
            default = kwargs['default']
            if isinstance(default, str):
                kwargs['default'] = Token(default)
        super(TokenField, self).__init__(*args, **kwargs)

    def to_python(self, value):
        if isinstance(value, str) and value:
            return Token(value)
        return value

    def get_prep_value(self, value):
        if not isinstance(value, str) and value:
            return value.token
        return super(TokenField, self).get_prep_value(value)


try:
    """
    Django 1.6 migrations
    """
    from south.modelsinspector import add_introspection_rules
    add_introspection_rules([], ["^viewflow\.fields\.FlowReferenceField"])
    add_introspection_rules([(
        (TaskReferenceField,),
        [],
        {'default': ["default", {'ignore_if': 'default'}]}  # HACK always ignore b/c south have no support for callables
    )], ["^viewflow\.fields\.TaskReferenceField"])
    add_introspection_rules([(
        (TokenField,),
        [],
        {'default': ["default.token", {}]}
    )], ["^viewflow\.fields\.TokenField"])

except ImportError:
    pass
