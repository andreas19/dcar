History
-------

 - Add parameter block to Bus.block()
 - Add field is_signal to MessageInfo
 - The handler functions for incoming method calls and signals are not executed
   in the same thread as the recv-loop any more but in a separate thread
   sequentially

**2019-06-03 (0.1.0)**
 - First public release
