from rest_framework import serializers
from rest_framework.settings import api_settings
from decimal import Decimal, localcontext
import copy


class BaseSerializableField(serializers.Field):
    def __init__(self, key=None, transformations=None, **kwargs):
        self.kwargs = kwargs
        self.export_override = None
        self.import_methods = []
        self.key = key
        self.precision = kwargs.pop('precision', None)  # Precision to use for multiply / divide operations
        self.export_formatter = kwargs.pop('export_formatter', None)  # Formatter to use in to_representation

        if transformations is not None:
            # This pops any transformation kwargs off (e.g multiply) , since the DRF doesn't expect them as kwargs
            self.listen_for_transformations(transformations, kwargs)

        # If we explicitly pass in a method to execute on export, we want to make sure it overrides the default
        # behavior, so we store it here and check for it on field to_representation calls
        # e.g. MethodField('xyz', multiply=100, export=(IntegerField.divide, 1000))
        if 'export' in kwargs:
            self.export_override = kwargs.get('export')
            if not callable(self.export_override):
                raise TypeError("export must be a callable")

        super(BaseSerializableField, self).__init__(**kwargs)

    def to_internal_value(self, data):
        """
        external representation --> our representation (model)

        :param data:
        :return:
        """
        result = data

        # If we've got a key, we want to check it for dot notation, e.g. master_variation.price.amount
        if self.key is not None and isinstance(result, dict):
            for step in self.key.split('.'):
                result = result.get(step)

        # Execute any transform methods set by field initializations,
        # e.g. IntegerField('rate', multiply=100) sets import_methods=[(multiply, 100)]
        for transform_method, param in self.import_methods:
            # We let the calling transform function handle the conversion to whatever it needs (float, decimal, etc)
            result = transform_method(result, param, precision=self.precision)

        # After it's fully transformed back to its internal state, de-serialize normally, and return it
        return super(BaseSerializableField, self).to_internal_value(result)

    def listen_for_transformations(self, transformation_list, kwargs):
        for import_method in set(transformation_list).intersection(kwargs.keys()):
            if hasattr(self.__class__, import_method) and callable(getattr(self.__class__, import_method)):
                method = getattr(self.__class__, import_method)
                params = kwargs.pop(import_method)
                self.import_methods.append((method, params))

    def to_representation(self, obj): # our representation --> external representation
        # Serialize as normal
        result = super(BaseSerializableField, self).to_representation(obj)

        # If we specified an override on exporting, we want to run that instead of reversing the import methods
        if self.export_override:
            # Export override (e.g. export=[(Multiply, 1000)])
            for transform_override, param in self.export_override:
                result = transform_override(result, param)
        else:
            # Otherwise, just call all the original transform methods (in order) but with reverse=True to undo them
            for transform_method, param in self.import_methods:
                result = transform_method(result, param, reverse=True)

        if self.export_formatter is not None:
            result = self.export_formatter(result)

        return result

    # Allows fetching derived classes from this class
    def _field_type(self):
        return self.__class__

    def _rest_framework_field(self):
        # Since we're using multiple inheritance, our base class is base[0] and the rest_framework class is base[1] here
        if getattr(self, 'is_serializer_field', False):
            return self.__class__.__bases__[0].__bases__[1]
        else:
            return self.__class__.__bases__[1]


class IntegerField(BaseSerializableField, serializers.IntegerField):
    def __init__(self, key=None, **kwargs):
        # Define transformations we are going to listen for
        transformations = ['multiply', 'divide', 'add', 'subtract']

        # Pass through to our BaseSerializableField __init__ to set up key parsing
        super(IntegerField, self).__init__(key=key, transformations=transformations, **kwargs)

    @staticmethod
    def multiply(operand, value, reverse=False, precision=None):
        with localcontext() as ctx:
            if precision is not None:
                # If a precision is specified, limit our multiplication / division to that precision
                ctx.prec = precision  # This is the TOTAL number of digits (not just decimal places)

            # Always use Decimal for these operations so we can control the precision
            operand = Decimal(operand)

            if reverse:
                return operand / value

            return int(operand * value)

    # todo: revisit and re-implement when we need to use this transformation
    # @staticmethod
    # def divide(operand, value, reverse=False, precision=None):
    #     if precision is not None:
    #         # If a precision is specified, limit our division / multiplication to that precision
    #         getcontext().prec = precision  # This is the TOTAL number of significant digits (not just decimal places
    #
    #     operand = Decimal(operand)
    #
    #     return operand / value if not reverse else operand * value

    @staticmethod
    def add(operand, value, reverse=False):
        return operand + value if not reverse else operand - value

    @staticmethod
    def subtract(operand, value, reverse=False):
        return operand - value if not reverse else operand + value

    def bind(self, field_name, parent):
        super(IntegerField, self).bind(field_name, parent)

        if self.key and self.key != self.field_name:
            self.original_field_name = self.field_name
            self.field_name = self.key


class CharField(BaseSerializableField, serializers.CharField):
    def __init__(self, key=None, **kwargs):
        # Never trim whitespace - DRF trims by default
        kwargs['trim_whitespace'] = False

        super(CharField, self).__init__(key, **kwargs)

    def bind(self, field_name, parent):
        super(CharField, self).bind(field_name, parent)

        if self.key and self.key != self.field_name:
            self.original_field_name = self.field_name
            self.field_name = self.key

class BooleanField(BaseSerializableField, serializers.BooleanField):  # Mix BaseSerializeableField in with BooleanField
    pass


class SerializerMethodField(BaseSerializableField, serializers.SerializerMethodField): # Mix BaseSerializeableField in
    pass


class ListField(BaseSerializableField, serializers.ListField):
    pass


class DateTimeField(BaseSerializableField, serializers.DateTimeField):
    pass


class BindableListSerializer(serializers.ListSerializer):
    def __init__(self, key=None, **kwargs):
        self.key = key
        super(BindableListSerializer, self).__init__(**kwargs)

    def to_internal_value(self, data):
        """
        List of dicts of native values <- List of dicts of primitive datatypes.
        """
        if serializers.html.is_html_input(data):
            data = serializers.html.parse_html_list(data)

        if not isinstance(data, list):
            message = self.error_messages['not_a_list'].format(
                input_type=type(data).__name__
            )
            raise serializers.ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            })

        if not self.allow_empty and len(data) == 0:
            message = self.error_messages['empty']
            raise serializers.ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            })

        ret = []
        errors = []

        for item in data:
            try:
                validated = self.child.run_validation(item)
            except serializers.ValidationError as exc:
                errors.append(exc.detail)
            else:
                ret.append(validated)
                errors.append({})

        if any(errors):
            raise serializers.ValidationError(errors)

        return ret


# A ModelSerializer that allows overriding which key a field is bound to
class BindableModelSerializer(serializers.ModelSerializer):
    def __init__(self, key=None, **kwargs):
        self.key = key

        super(BindableModelSerializer, self).__init__(**kwargs)

    @classmethod
    def many_init(cls, *args, **kwargs):
        """
        This method implements the creation of a `ListSerializer` parent
        class when `many=True` is used. You can customize it if you need to
        control which keyword arguments are passed to the parent, and
        which are passed to the child.

        Note that we're over-cautious in passing most arguments to both parent
        and child classes in order to try to cover the general case. If you're
        overriding this method you'll probably want something much simpler, eg:

        @classmethod
        def many_init(cls, *args, **kwargs):
            kwargs['child'] = cls()
            return CustomListSerializer(*args, **kwargs)
        """

        allow_empty = kwargs.pop('allow_empty', None)
        child_serializer = cls(**kwargs)
        list_kwargs = {
            'child': child_serializer,
        }

        if allow_empty is not None:
            list_kwargs['allow_empty'] = allow_empty
        list_kwargs.update({
            key: value for key, value in kwargs.items()
            if key in serializers.LIST_SERIALIZER_KWARGS
        })

        meta = getattr(cls, 'Meta', None)
        list_serializer_class = getattr(meta, 'list_serializer_class', BindableListSerializer)

        return list_serializer_class(*args, **list_kwargs)

    def to_internal_value(self, data):
        """
        Dict of native values <- Dict of primitive datatypes.
        """

        if not isinstance(data, dict):
            message = self.error_messages['invalid'].format(
                datatype=type(data).__name__
            )
            raise serializers.ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            })

        ret = serializers.OrderedDict()
        errors = serializers.OrderedDict()
        fields = self._writable_fields

        for field in fields:
            validate_method = getattr(self, 'validate_' + field.field_name, None)
            result = copy.copy(data)
            if hasattr(field, 'key') and field.key is not None:
                if isinstance(field, BindableListSerializer) or isinstance(field, serializers.Field):

                    for step in field.key.split('.'):
                        result = result.get(step, {})

                    if not isinstance(result, dict):
                        result = {field.field_name: result}

                primitive_value = field.get_value(result)

            try:
                validated_value = field.run_validation(primitive_value)
                if validate_method is not None:
                    validated_value = validate_method(validated_value)
            except serializers.ValidationError as exc:
                errors[field.field_name] = exc.detail
            except serializers.DjangoValidationError as exc:
                errors[field.field_name] = list(exc.messages)
            except serializers.SkipField:
                pass
            else:
                serializers.set_value(ret, field.source_attrs, validated_value)

        if errors:
            raise serializers.ValidationError(errors)

        return ret

    def bind(self, field_name, parent):
        super(BindableModelSerializer, self).bind(field_name, parent)

        if self.key and self.key != self.field_name:
            self.original_field_name = self.field_name
            self.field_name = self.key
