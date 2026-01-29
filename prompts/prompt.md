You are an expert competitive programmer. Please solve the following problem:

**Resonance Carousel**

Time Limit: **2 seconds**

Memory Limit: **64 MB**

On a giant rotating disk sit n crystal pylons arranged in a ring. Each pylon i has an initial charge a_i. You may perform pulses: in one pulse, choose a contiguous arc of pylons on the current linear view (a segment that does not wrap) and increase every pylon on that arc by 1. If the chosen arc has length L, that pulse grants $L^2 + \alpha \cdot L$ resonance points.

For a fixed cyclic shift s (viewing the array as $[a_s, a_{s+1}, \dots, a_{s+n-1}]$ with indices modulo n), you want to reach a state where all charges are equal using the minimum possible number of pulses; among all such minimum-pulse strategies, maximize the total resonance points. Since the carousel is round, you must compute this result for every cyclic shift s from 0 to n−1.

For each shift, output:
- cnt: the minimum number of pulses needed to make all charges equal,
- cost: the maximum total resonance points achievable using exactly cnt pulses, then taken modulo $10^9+7$.
Take the modulo only after maximizing the total resonance points.

Segments are chosen on the linear array of the current shift and cannot wrap around in that view.

**Input Format:-**

- Multiple test cases.
- The first line contains an integer t, the number of test cases.
- For each test case:
  - A line with two integers n and alpha.
  - A line with n integers $a_0, a_1, \dots, a_{n-1}$.

**Output Format:-**

For each test case, print n lines. For every cyclic shift s from 0 to n−1, print two integers: cnt and cost (modulo $10^9+7$), separated by a space.

**Constraints:-**

- $1 \le t \le 2 \cdot 10^4$
- $1 \le n \le 10^6$
- $0 \le \text{alpha} \le 10^9$
- $1 \le a_i \le 10^9$
- The sum of n over all test cases does not exceed $10^6$
**Examples:-**
 - **Input:**
```
1
8 3
9 9 9 1 9 9 9 9
```

 - **Output:**
```
8 32
8 32
8 32
8 32
8 32
8 32
8 32
8 32
```

 - **Input:**
```
1
3 1000000000
1 1000000000 999999999
```

 - **Output:**
```
1000000000 42
999999999 44
999999999 44
```

**Note:-**
  
In the first example, $n=8$, $\alpha=3$, and $a=[9,9,9,1,9,9,9,9]$.
- The target level is $c=\max(a)=9$. Deficits are $h=c-a=[0,0,0,8,0,0,0,0]$.
- For every shift, each of the $8$ layers ($k=1,\dots,8$) has exactly one component of length $1$ (the lone low pylon), so $\text{cnt}=8$ for all shifts.
- Cost splits as $\sum L^2 + \alpha \sum h$. Here $\sum L^2=8\cdot 1^2=8$ and $\sum h=8$, so total cost $=8+3\cdot 8=32$. Hence all $8$ lines are "$8\ 32$".

In the second example, $n=3$, $\alpha=10^9$, and $a=[1,10^9,999999999]$, so $c=10^9$ and deficits $h=[999999999,0,1]$ up to rotation. The linear term $\alpha\sum h=\alpha\cdot 10^9=(10^9)^2$ is the same for every shift; only $\sum L^2$ changes with the cut.
- Shift $s=0$: $b=[1,10^9,999999999]$, $h=[999999999,0,1]$.
  - Layer $k=1$: two separate singletons $\Rightarrow$ $2$ pulses of length $1$.
  - Layers $k=2,\dots,999999999$: one singleton each $\Rightarrow$ $999999998$ more pulses.
  - Thus $\text{cnt}=10^9$ and $\sum L^2=2\cdot 1^2+999999998\cdot 1^2=10^9$.
  - Total cost modulo $10^9+7$:
    $$ (10^9)^2+10^9 \equiv 49+10^9 \equiv 42 \pmod{10^9+7}. $$
- Shifts $s=1$ and $s=2$: at layer $k=1$ the positive deficits are adjacent in the linear view (one component of length $2$), and for $k=2,\dots,999999999$ there is one singleton each.
  - Thus $\text{cnt}=999999999$ and $\sum L^2=2^2+999999998\cdot 1^2=1000000002$.
  - Total cost modulo $10^9+7$:
    $$ (10^9)^2+1000000002 \equiv 49+1000000002 \equiv 44 \pmod{10^9+7}. $$

First analyze the problem, then provide your solution in C++. Consider edge cases, time complexity, and space complexity. Make sure your solution handles all constraints mentioned in the problem. Your final solution should be a complete, compilable C++ program.