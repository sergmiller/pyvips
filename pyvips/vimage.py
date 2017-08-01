# wrap VipsImage

from __future__ import division

import logging
import numbers

from pyvips import *

logger = logging.getLogger(__name__)

ffi.cdef('''
    typedef struct _VipsImage {
        VipsObject parent_instance;

        // opaque
    } VipsImage;

    const char* vips_foreign_find_load (const char* name);
    const char* vips_foreign_find_load_buffer (const void* data, size_t size);
    const char* vips_foreign_find_save (const char* name);
    const char* vips_foreign_find_save_buffer (const char* suffix);

    VipsImage* vips_image_new_matrix_from_array (int width, int height,
            const double* array, int size);

    VipsImage* vips_image_copy_memory (VipsImage* image);

    GType vips_image_get_typeof (const VipsImage* image, 
        const char* name);
    int vips_image_get (const VipsImage* image, 
        const char* name, GValue* value_copy);
    void vips_image_set (VipsImage* image, const char* name, GValue* value);
    int vips_image_remove (VipsImage* image, const char* name);

    char* vips_filename_get_filename (const char* vips_filename);
    char* vips_filename_get_options (const char* vips_filename);

''')

# either a single number, or a table of numbers
def _is_pixel(value):
    return (isinstance(value, numbers.Number) or 
            (isinstance(vaue, list) and not isinstance(value, Image)))

# test for rectangular array of something
def _is_2D(array):
    if not isinstance(array, list):
        return False

    for x in array:
        if not isinstance(x, list):
            return False
        if len(x) != len(array[0]):
            return False

    return True

def _call_enum(image, other, base, operation):
    if isinstance(other, numbers.Number):
        return Operation.call(base + '_const', image, operation, [other])
    elif _is_pixel(other):
        return Operation.call(base + '_const', image, operation, other)
    else:
        return Operation.call(base, image, other, operation)

class Image(VipsObject):

    # private static

    @staticmethod
    def imageize(self, value):
        # careful! self can be None if value is a 2D array
        if isinstance(value, Image):
            return value
        elif _is_2D(value):
            return Image.new_from_array(value)
        else:
            return self.new_from_image(value)

    def __init__(self, pointer):
        logger.debug('Image.__init__: pointer = {0}'.format(pointer))
        super(Image, self).__init__(pointer)

    # constructors

    @staticmethod
    def new_from_file(vips_filename, **kwargs):
        filename = vips_lib.vips_filename_get_filename(vips_filename)
        options = vips_lib.vips_filename_get_options(vips_filename)
        name = vips_lib.vips_foreign_find_load(filename)
        if name == ffi.NULL:
            raise Error('unable to load from file {0}'.format(vips_filename))

        return Operation.call(ffi.string(name), ffi.string(filename), 
                              string_options = ffi.string(options), **kwargs)

    @staticmethod
    def new_from_buffer(data, options, **kwargs):
        name = vips_lib.vips_foreign_find_load_buffer(data)
        if name == ffi.NULL:
            raise Error('unable to load from buffer')

        return Operation.call(ffi.string(name), data, 
                              string_options = ffi.string(options), **kwargs)

    @staticmethod
    def new_from_array(array, scale = 1.0, offset = 0.0):
        if not _is_2D(array):
            array = [array]

        height = len(array)
        width = len(array[1])

        n = width * height
        a = ffi.new("double[]", n)
        for y in range(0, height):
            for x in range(0, width):
                a[x + y * width] = array[y][x]

        vi = vips_lib.vips_image_new_matrix_from_array(width, height, a, n)
        image = Image(vi)

        image.set_type(GValue.gdouble_type, "scale", scale)
        image.set_type(GValue.gdouble_type, "offset", offset)

        return image

    def new_from_image(self, value):
        pixel = (Image.black(1, 1) + value).cast(self.format)
        image = pixel.embed(0, 0, base_image.width, base_image.height,
            extend = "copy")
        image = image.copy(interpretation = self.interpretation,
                           xres = self.xres,
                           yres =  self.yres,
                           xoffset = self.xoffset,
                           yoffset = self.yoffset)

        return image

    def copy_memory(self):
        vi = vips.vips_image_copy_memory(self.pointer)
        if vi == ffi.NULL:
            raise Error('unable to copy to memory')

        return Image.new(vi)

    # writers

    def write_to_file(self, vips_filename, **kwargs):
        filename = vips_lib.vips_filename_get_filename(vips_filename)
        options = vips_lib.vips_filename_get_options(vips_filename)
        name = vips_lib.vips_foreign_find_save(filename)
        if name == ffi.NULL:
            raise Error('unable to write to file {}'.format(vips_filename))

        return Operation.call(ffi.string(name), self, filename,
                              string_options = ffi.string(options), **kwargs)

    def write_to_buffer(self, format_string, **kwargs):
        options = vips_lib.vips_filename_get_options(format_string)
        name = vips_lib.vips_foreign_find_save_buffer(format_string)
        if name == ffi.NULL:
            raise Error('unable to write to buffer')

        return Operation.call(ffi.string(name), self, 
                              string_options = ffi.string(options), **kwargs)

    # get/set metadata

    def get_typeof(self, name):
        return vips_lib.vips_image_get_typeof(self.pointer, name)

    def get(self, name):
        gv = GValue()
        result = vips_lib.vips_image_get(self.pointer, name, gv)
        if result != 0:
            raise Error('unable to get {0}'.format(name))

        return gv.get()

    def set_type(self, gtype, name, value):
        gv = GValue()
        gv.init(gtype)
        gv.set(value)
        vips_lib.vips_image_set(self.pointer, name, gv)

    def set(self, name, value):
        gtype = self.get_typeof(name)
        self.set_type(gtype, name, value)

    def remove(self, name):
        return vips_lib.vips_image_remove(self.pointer, name) != 0

    def __getattr__(self, name):
        logger.debug('Image.__getattr__ {0}'.format(name))

        # look up in props first (but not metadata)
        if super(Image, self).get_typeof(name) != 0:
            return super(Image, self).get(name)

        def call_function(*args, **kwargs):
            return Operation.call(name, self, *args, **kwargs)

        return call_function

    # support with in the most trivial way

    def __enter__(self):
        return self
    def __exit__(self, type, value, traceback):
        pass

    # access as an array
    def __getitem__(self, arg):
        if isinstance(arg, slice):
            i = 0
            if arg.start != None:
                i = arg.start

            n = self.bands - i
            if arg.stop != None:
                if arg.stop < 0:
                    n = self.bands + arg.stop - i
                else:
                    n = arg.stop - i
        elif isinstance(arg, int):
            i = arg
            n = 1
        else:
            raise TypeError

        if i < 0:
            i = self.bands + i

        if i < 0 or i >= self.bands:
            raise IndexError

        return self.extract_band(i, n = n)

    # overload () to mean fetch pixel
    def __call__(self, x, y):
        return self.getpoint(x, y)

    # operator overloads

    def __add__(self, other):
        if isinstance(other, Vips.Image):
            return self.add(other)
        else:
            return self.linear(1, other)

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        if isinstance(other, Vips.Image):
            return self.subtract(other)
        else:
            return self.linear(1, smap(lambda x: -1 * x, other))

    def __rsub__(self, other):
        return self.linear(-1, other)

    def __mul__(self, other):
        if isinstance(other, Vips.Image):
            return self.multiply(other)
        else:
            return self.linear(other, 0)

    def __rmul__(self, other):
        return self.__mul__(other)

    # a / const has always been a float in vips, so div and truediv are the 
    # same
    def __div__(self, other):
        if isinstance(other, Vips.Image):
            return self.divide(other)
        else:
            return self.linear(smap(lambda x: 1.0 / x, other), 0)

    def __rdiv__(self, other):
        return (self ** -1) * other

    def __truediv__(self, other):
        return self.__div__(other)

    def __rtruediv__(self, other):
        return self.__rdiv__(other)

    def __floordiv__(self, other):
        if isinstance(other, Vips.Image):
            return self.divide(other).floor()
        else:
            return self.linear(smap(lambda x: 1.0 / x, other), 0).floor()

    def __rfloordiv__(self, other):
        return ((self ** -1) * other).floor()

    def __mod__(self, other):
        if isinstance(other, Vips.Image):
            return self.remainder(other)
        else:
            return self.remainder_const(other)

    def __pow__(self, other):
        return _call_enum(self, "math2", Vips.OperationMath2.POW, other)

    def __rpow__(self, other):
        return _call_enum(self, "math2", Vips.OperationMath2.WOP, other)

    def __abs__(self):
        return self.abs()

    def __lshift__(self, other):
        return _call_enum(self, "boolean", Vips.OperationBoolean.LSHIFT, other)

    def __rshift__(self, other):
        return _call_enum(self, "boolean", Vips.OperationBoolean.RSHIFT, other)

    def __and__(self, other):
        return _call_enum(self, "boolean", Vips.OperationBoolean.AND, other)

    def __rand__(self, other):
        return self.__and__(other)

    def __or__(self, other):
        return _call_enum(self, "boolean", Vips.OperationBoolean.OR, other)

    def __ror__(self, other):
        return self.__or__(other)

    def __xor__(self, other):
        return _call_enum(self, "boolean", Vips.OperationBoolean.EOR, other)

    def __rxor__(self, other):
        return self.__xor__(other)

    def __neg__(self):
        return -1 * self

    def __pos__(self):
        return self

    def __invert__(self):
        return self ^ -1

    def __gt__(self, other):
        return _call_enum(self, 
                          "relational", Vips.OperationRelational.MORE, other)

    def __ge__(self, other):
        return _call_enum(self, 
                          "relational", Vips.OperationRelational.MOREEQ, other)

    def __lt__(self, other):
        return _call_enum(self, 
                          "relational", Vips.OperationRelational.LESS, other)

    def __le__(self, other):
        return _call_enum(self, 
                          "relational", Vips.OperationRelational.LESSEQ, other)

    def __eq__(self, other):
        # _eq version allows comparison to None
        return _call_enum_eq(self, 
                             "relational", Vips.OperationRelational.EQUAL, other)

    def __ne__(self, other):
        # _eq version allows comparison to None
        return _call_enum_eq(self, 
                             "relational", Vips.OperationRelational.NOTEQ, other)

    def floor(self):
        """Return the largest integral value not greater than the argument."""
        return self.round(Vips.OperationRound.FLOOR)

    def ceil(self):
        """Return the smallest integral value not less than the argument."""
        return self.round(Vips.OperationRound.CEIL)

    def rint(self):
        """Return the nearest integral value."""
        return self.round(Vips.OperationRound.RINT)

    def bandand(self):
        """AND image bands together."""
        return self.bandbool(Vips.OperationBoolean.AND)

    def bandor(self):
        """OR image bands together."""
        return self.bandbool(Vips.OperationBoolean.OR)

    def bandeor(self):
        """EOR image bands together."""
        return self.bandbool(Vips.OperationBoolean.EOR)

    def bandsplit(self):
        """Split an n-band image into n separate images."""
        return [x for x in self]

    def bandjoin(self, other):
        """Append a set of images or constants bandwise."""
        if not isinstance(other, list):
            other = [other]

        # if [other] is all numbers, we can use bandjoin_const
        non_number = next((x for x in other 
                            if not isinstance(x, numbers.Number)), 
                           None)

        if non_number == None:
            return self.bandjoin_const(other)
        else:
            return _call_base("bandjoin", [[self] + other], {})

    def bandrank(self, other, **kwargs):
        """Band-wise rank filter a set of images."""
        if not isinstance(other, list):
            other = [other]

        return _call_base("bandrank", [[self] + other], kwargs)

    def maxpos(self):
        """Return the coordinates of the image maximum."""
        v, opts = self.max(x = True, y = True)
        x = opts['x']
        y = opts['y']
        return v, x, y

    def minpos(self):
        """Return the coordinates of the image minimum."""
        v, opts = self.min(x = True, y = True)
        x = opts['x']
        y = opts['y']
        return v, x, y

    def real(self):
        """Return the real part of a complex image."""
        return self.complexget(Vips.OperationComplexget.REAL)

    def imag(self):
        """Return the imaginary part of a complex image."""
        return self.complexget(Vips.OperationComplexget.IMAG)

    def polar(self):
        """Return an image converted to polar coordinates."""
        return run_cmplx(lambda x: x.complex(Vips.OperationComplex.POLAR), self)

    def rect(self):
        """Return an image converted to rectangular coordinates."""
        return run_cmplx(lambda x: x.complex(Vips.OperationComplex.RECT), self)

    def conj(self):
        """Return the complex conjugate of an image."""
        return self.complex(Vips.OperationComplex.CONJ)

    def sin(self):
        """Return the sine of an image in degrees."""
        return self.math(Vips.OperationMath.SIN)

    def cos(self):
        """Return the cosine of an image in degrees."""
        return self.math(Vips.OperationMath.COS)

    def tan(self):
        """Return the tangent of an image in degrees."""
        return self.math(Vips.OperationMath.TAN)

    def asin(self):
        """Return the inverse sine of an image in degrees."""
        return self.math(Vips.OperationMath.ASIN)

    def acos(self):
        """Return the inverse cosine of an image in degrees."""
        return self.math(Vips.OperationMath.ACOS)

    def atan(self):
        """Return the inverse tangent of an image in degrees."""
        return self.math(Vips.OperationMath.ATAN)

    def log(self):
        """Return the natural log of an image."""
        return self.math(Vips.OperationMath.LOG)

    def log10(self):
        """Return the log base 10 of an image."""
        return self.math(Vips.OperationMath.LOG10)

    def exp(self):
        """Return e ** pixel."""
        return self.math(Vips.OperationMath.EXP)

    def exp10(self):
        """Return 10 ** pixel."""
        return self.math(Vips.OperationMath.EXP10)

    def erode(self, mask):
        """Erode with a structuring element."""
        return self.morph(mask, Vips.OperationMorphology.ERODE)

    def dilate(self, mask):
        """Dilate with a structuring element."""
        return self.morph(mask, Vips.OperationMorphology.DILATE)

    def median(self, size):
        """size x size median filter."""
        return self.rank(size, size, (size * size) / 2)

    def fliphor(self):
        """Flip horizontally."""
        return self.flip(Vips.Direction.HORIZONTAL)

    def flipver(self):
        """Flip vertically."""
        return self.flip(Vips.Direction.VERTICAL)

    def rot90(self):
        """Rotate 90 degrees clockwise."""
        return self.rot(Vips.Angle.D90)

    def rot180(self):
        """Rotate 180 degrees."""
        return self.rot(Vips.Angle.D180)

    def rot270(self):
        """Rotate 270 degrees clockwise."""
        return self.rot(Vips.Angle.D270)

    # we need different imageize rules for this operator ... we need to 
    # imageize th and el to match each other first
    def ifthenelse(self, th, el, **kwargs):
        for match_image in [th, el, self]:
            if isinstance(match_image, Image):
                break

        if not isinstance(th, Image):
            th = imageize(match_image, th)
        if not isinstance(el, Image):
            el = imageize(match_image, el)

        return Operation.call("ifthenelse", self, th, el, **kwargs)

__all__ = ['Image']