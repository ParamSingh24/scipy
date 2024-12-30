import inspect
import pytest
import numpy as np
from numpy.testing import assert_allclose
from scipy import linalg


real_floating = [np.float32, np.float64]
complex_floating = [np.complex64, np.complex128]
floating = real_floating + complex_floating


def get_random(shape, *, dtype, rng):
    A = rng.random(shape)
    if np.issubdtype(dtype, np.complexfloating):
        A = A + rng.random(shape) * 1j
    return A.astype(dtype)

def get_nearly_hermitian(shape, dtype, atol, rng):
    # Generate a batch of nearly Hermitian matrices with specified
    # `shape` and `dtype`. `atol` controls the level of noise in
    # Hermitian-ness to by generated by `rng`.
    A = rng.random(shape).astype(dtype)
    At = np.conj(A.swapaxes(-1, -2))
    noise = rng.standard_normal(size=A.shape).astype(dtype) * atol
    return A + At + noise


class TestBatch:
    # Test batch support for most linalg functions

    def batch_test(self, fun, arrays, *, core_dim=2, n_out=1, kwargs=None, dtype=None,
                   broadcast=True, check_kwargs=True):
        # Check that all outputs of batched call `fun(A, **kwargs)` are the same
        # as if we loop over the separate vectors/matrices in `A`. Also check
        # that `fun` accepts `A` by position or keyword and that results are
        # identical. This is important because the name of the array argument
        # is manually specified to the decorator, and it's easy to mess up.
        # However, this makes it hard to test positional arguments passed
        # after the array, so we test that separately for a few functions to
        # make sure the decorator is working as it should.

        kwargs = {} if kwargs is None else kwargs
        parameters = list(inspect.signature(fun).parameters.keys())
        arrays = (arrays,) if not isinstance(arrays, tuple) else arrays

        # Identical results when passing argument by keyword or position
        res2 = fun(*arrays, **kwargs)
        if check_kwargs:
            res1 = fun(**dict(zip(parameters, arrays)), **kwargs)
            for out1, out2 in zip(res1, res2):  # even a single array is iterable...
                np.testing.assert_equal(out1, out2)

        # Check results vs looping over
        res = (res2,) if n_out == 1 else res2
        # This is not the general behavior (only batch dimensions get
        # broadcasted by the decorator) but it's easier for testing.
        if broadcast:
            arrays = np.broadcast_arrays(*arrays)
        batch_shape = arrays[0].shape[:-core_dim]
        for i in range(batch_shape[0]):
            for j in range(batch_shape[1]):
                arrays_ij = (array[i, j] for array in arrays)
                ref = fun(*arrays_ij, **kwargs)
                ref = ((np.asarray(ref),) if n_out == 1 else
                       tuple(np.asarray(refk) for refk in ref))
                for k in range(n_out):
                    assert_allclose(res[k][i, j], ref[k])
                    assert np.shape(res[k][i, j]) == ref[k].shape

        for k in range(len(ref)):
            out_dtype = ref[k].dtype if dtype is None else dtype
            assert res[k].dtype == out_dtype

        return res2  # return original, non-tuplized result

    @pytest.fixture
    def rng(self):
        return np.random.default_rng(8342310302941288912051)

    @pytest.mark.parametrize('dtype', floating)
    def test_expm_cond(self, dtype, rng):
        A = rng.random((5, 3, 4, 4)).astype(dtype)
        self.batch_test(linalg.expm_cond, A)

    @pytest.mark.parametrize('dtype', floating)
    def test_issymmetric(self, dtype, rng):
        A = get_nearly_hermitian((5, 3, 4, 4), dtype, 3e-4, rng)
        res = self.batch_test(linalg.issymmetric, A, kwargs=dict(atol=1e-3))
        assert not np.all(res)  # ensure test is not trivial: not all True or False;
        assert np.any(res)      # also confirms that `atol` is passed to issymmetric

    @pytest.mark.parametrize('dtype', floating)
    def test_ishermitian(self, dtype, rng):
        A = get_nearly_hermitian((5, 3, 4, 4), dtype, 3e-4, rng)
        res = self.batch_test(linalg.ishermitian, A, kwargs=dict(atol=1e-3))
        assert not np.all(res)  # ensure test is not trivial: not all True or False;
        assert np.any(res)      # also confirms that `atol` is passed to ishermitian

    @pytest.mark.parametrize('dtype', floating)
    def test_diagsvd(self, dtype, rng):
        A = rng.random((5, 3, 4)).astype(dtype)
        res1 = self.batch_test(linalg.diagsvd, A, kwargs=dict(M=6, N=4), core_dim=1)
        # test that `M, N` can be passed by position
        res2 = linalg.diagsvd(A, 6, 4)
        np.testing.assert_equal(res1, res2)

    @pytest.mark.parametrize('fun', [linalg.inv, linalg.sqrtm, linalg.signm,
                                     linalg.sinm, linalg.cosm, linalg.tanhm,
                                     linalg.sinhm, linalg.coshm, linalg.tanhm,
                                     linalg.pinv, linalg.pinvh, linalg.orth])
    @pytest.mark.parametrize('dtype', floating)
    def test_matmat(self, fun, dtype, rng):  # matrix in, matrix out
        A = get_random((5, 3, 4, 4), dtype=dtype, rng=rng)
        self.batch_test(fun, A)

    @pytest.mark.parametrize('dtype', floating)
    def test_null_space(self, dtype, rng):
        A = get_random((5, 3, 4, 6), dtype=dtype, rng=rng)
        self.batch_test(linalg.null_space, A)

    @pytest.mark.parametrize('dtype', floating)
    def test_funm(self, dtype, rng):
        A = get_random((2, 4, 3, 3), dtype=dtype, rng=rng)
        self.batch_test(linalg.funm, A, kwargs=dict(func=np.sin))

    @pytest.mark.parametrize('dtype', floating)
    def test_fractional_matrix_power(self, dtype, rng):
        A = get_random((2, 4, 3, 3), dtype=dtype, rng=rng)
        res1 = self.batch_test(linalg.fractional_matrix_power, A, kwargs={'t':1.5})
        # test that `t` can be passed by position
        res2 = linalg.fractional_matrix_power(A, 1.5)
        np.testing.assert_equal(res1, res2)

    @pytest.mark.parametrize('disp', [False, True])
    @pytest.mark.parametrize('dtype', floating)
    def test_logm(self, dtype, disp):
        # One test failed absolute tolerance with default random seed
        rng = np.random.default_rng(89940026998903887141749720079406074936)
        A = get_random((5, 3, 4, 4), dtype=dtype, rng=rng)
        A = A + 3*np.eye(4)  # avoid complex output for real input
        n_out = 1 if disp else 2
        res1 = self.batch_test(linalg.logm, A, n_out=n_out, kwargs=dict(disp=disp))
        # test that `disp` can be passed by position
        res2 = linalg.logm(A, disp)
        for res1i, res2i in zip(res1, res2):
            np.testing.assert_equal(res1i, res2i)

    @pytest.mark.parametrize('dtype', floating)
    def test_pinv(self, dtype, rng):
        A = get_random((5, 3, 4, 4), dtype=dtype, rng=rng)
        self.batch_test(linalg.pinv, A, n_out=2, kwargs=dict(return_rank=True))

    @pytest.mark.parametrize('dtype', floating)
    def test_matrix_balance(self, dtype, rng):
        A = get_random((5, 3, 4, 4), dtype=dtype, rng=rng)
        self.batch_test(linalg.matrix_balance, A, n_out=2)
        self.batch_test(linalg.matrix_balance, A, n_out=2, kwargs={'separate':True})

    @pytest.mark.parametrize('dtype', floating)
    def test_bandwidth(self, dtype, rng):
        A = get_random((4, 4), dtype=dtype, rng=rng)
        A = np.asarray([np.triu(A, k) for k in range(-3, 3)]).reshape((2, 3, 4, 4))
        self.batch_test(linalg.bandwidth, A, n_out=2)

    @pytest.mark.parametrize('fun_n_out', [(linalg.cholesky, 1), (linalg.ldl, 3),
                                           (linalg.cho_factor, 2)])
    @pytest.mark.parametrize('dtype', floating)
    def test_ldl_cholesky(self, fun_n_out, dtype, rng):
        fun, n_out = fun_n_out
        A = get_nearly_hermitian((5, 3, 4, 4), dtype, 0, rng)  # exactly Hermitian
        A = A + 4*np.eye(4, dtype=dtype)  # ensure positive definite for Cholesky
        self.batch_test(fun, A, n_out=n_out)

    @pytest.mark.parametrize('compute_uv', [False, True])
    @pytest.mark.parametrize('dtype', floating)
    def test_svd(self, compute_uv, dtype, rng):
        A = get_random((5, 3, 2, 4), dtype=dtype, rng=rng)
        n_out = 3 if compute_uv else 1
        self.batch_test(linalg.svd, A, n_out=n_out, kwargs=dict(compute_uv=compute_uv))

    @pytest.mark.parametrize('fun', [linalg.polar, linalg.qr, linalg.rq])
    @pytest.mark.parametrize('dtype', floating)
    def test_polar_qr_rq(self, fun, dtype, rng):
        A = get_random((5, 3, 2, 4), dtype=dtype, rng=rng)
        self.batch_test(fun, A, n_out=2)

    @pytest.mark.parametrize('cdim', [(5,), (5, 4), (2, 3, 5, 4)])
    @pytest.mark.parametrize('dtype', floating)
    def test_qr_multiply(self, cdim, dtype, rng):
        A = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        c = get_random(cdim, dtype=dtype, rng=rng)
        res = linalg.qr_multiply(A, c, mode='left')
        q, r = linalg.qr(A)
        ref = q @ c
        atol = 1e-6 if dtype in {np.float32, np.complex64} else 1e-12
        assert_allclose(res[0], ref, atol=atol)
        assert_allclose(res[1], r, atol=atol)

    @pytest.mark.parametrize('uvdim', [[(5,), (3,)], [(4, 5, 2), (4, 3, 2)]])
    @pytest.mark.parametrize('dtype', floating)
    def test_qr_update(self, uvdim, dtype, rng):
        udim, vdim = uvdim
        A = get_random((4, 5, 3), dtype=dtype, rng=rng)
        u = get_random(udim, dtype=dtype, rng=rng)
        v = get_random(vdim, dtype=dtype, rng=rng)
        q, r = linalg.qr(A)
        res = linalg.qr_update(q, r, u, v)
        for i in range(4):
            qi, ri = q[i], r[i]
            ui, vi = (u, v) if u.ndim == 1 else (u[i], v[i])
            ref_i = linalg.qr_update(qi, ri, ui, vi)
            assert_allclose(res[0][i], ref_i[0])
            assert_allclose(res[1][i], ref_i[1])

    @pytest.mark.parametrize('udim', [(5,), (4, 3, 5)])
    @pytest.mark.parametrize('kdim', [(), (4,)])
    @pytest.mark.parametrize('dtype', floating)
    def test_qr_insert(self, udim, kdim, dtype, rng):
        A = get_random((4, 5, 5), dtype=dtype, rng=rng)
        u = get_random(udim, dtype=dtype, rng=rng)
        k = rng.integers(0, 5, size=kdim)
        q, r = linalg.qr(A)
        res = linalg.qr_insert(q, r, u, k)
        for i in range(4):
            qi, ri = q[i], r[i]
            ki = k if k.ndim == 0 else k[i]
            ui = u if u.ndim == 1 else u[i]
            ref_i = linalg.qr_insert(qi, ri, ui, ki)
            assert_allclose(res[0][i], ref_i[0])
            assert_allclose(res[1][i], ref_i[1])

    @pytest.mark.parametrize('kdim', [(), (4,)])
    @pytest.mark.parametrize('dtype', floating)
    def test_qr_delete(self, kdim, dtype, rng):
        A = get_random((4, 5, 5), dtype=dtype, rng=rng)
        k = rng.integers(0, 4, size=kdim)
        q, r = linalg.qr(A)
        res = linalg.qr_delete(q, r, k)
        for i in range(4):
            qi, ri = q[i], r[i]
            ki = k if k.ndim == 0 else k[i]
            ref_i = linalg.qr_delete(qi, ri, ki)
            assert_allclose(res[0][i], ref_i[0])
            assert_allclose(res[1][i], ref_i[1])

    @pytest.mark.parametrize('fun', [linalg.schur, linalg.lu_factor])
    @pytest.mark.parametrize('dtype', floating)
    def test_schur_lu(self, fun, dtype, rng):
        A = get_random((5, 3, 4, 4), dtype=dtype, rng=rng)
        self.batch_test(fun, A, n_out=2)

    @pytest.mark.parametrize('calc_q', [False, True])
    @pytest.mark.parametrize('dtype', floating)
    def test_hessenberg(self, calc_q, dtype, rng):
        A = get_random((5, 3, 4, 4), dtype=dtype, rng=rng)
        n_out = 2 if calc_q else 1
        self.batch_test(linalg.hessenberg, A, n_out=n_out, kwargs=dict(calc_q=calc_q))

    @pytest.mark.parametrize('eigvals_only', [False, True])
    @pytest.mark.parametrize('dtype', floating)
    def test_eig_banded(self, eigvals_only, dtype, rng):
        A = get_random((5, 3, 4, 4), dtype=dtype, rng=rng)
        n_out = 1 if eigvals_only else 2
        self.batch_test(linalg.eig_banded, A, n_out=n_out,
                        kwargs=dict(eigvals_only=eigvals_only))

    @pytest.mark.parametrize('dtype', floating)
    def test_eigvals_banded(self, dtype, rng):
        A = get_random((5, 3, 4, 4), dtype=dtype, rng=rng)
        self.batch_test(linalg.eigvals_banded, A)

    @pytest.mark.parametrize('two_in', [False, True])
    @pytest.mark.parametrize('fun_n_nout', [(linalg.eigh, 1), (linalg.eigh, 2),
                                            (linalg.eigvalsh, 1), (linalg.eigvals, 1)])
    @pytest.mark.parametrize('dtype', floating)
    def test_eigh(self, two_in, fun_n_nout, dtype, rng):
        fun, n_out = fun_n_nout
        A = get_nearly_hermitian((1, 3, 4, 4), dtype, 0, rng)  # exactly Hermitian
        B = get_nearly_hermitian((2, 1, 4, 4), dtype, 0, rng)  # exactly Hermitian
        B = B + 4*np.eye(4).astype(dtype)  # needs to be positive definite
        args = (A, B) if two_in else (A,)
        kwargs = dict(eigvals_only=True) if (n_out == 1 and fun==linalg.eigh) else {}
        self.batch_test(fun, args, n_out=n_out, kwargs=kwargs)

    @pytest.mark.parametrize('compute_expm', [False, True])
    @pytest.mark.parametrize('dtype', floating)
    def test_expm_frechet(self, compute_expm, dtype, rng):
        A = get_random((1, 3, 4, 4), dtype=dtype, rng=rng)
        E = get_random((2, 1, 4, 4), dtype=dtype, rng=rng)
        n_out = 2 if compute_expm else 1
        self.batch_test(linalg.expm_frechet, (A, E), n_out=n_out,
                        kwargs=dict(compute_expm=compute_expm))

    @pytest.mark.parametrize('dtype', floating)
    def test_subspace_angles(self, dtype, rng):
        A = get_random((1, 3, 4, 3), dtype=dtype, rng=rng)
        B = get_random((2, 1, 4, 3), dtype=dtype, rng=rng)
        self.batch_test(linalg.subspace_angles, (A, B))
        # just to show that A and B don't need to be broadcastable
        M, N, K = 4, 5, 3
        A = get_random((1, 3, M, N), dtype=dtype, rng=rng)
        B = get_random((2, 1, M, K), dtype=dtype, rng=rng)
        assert linalg.subspace_angles(A, B).shape == (2, 3, min(N, K))

    @pytest.mark.parametrize('fun', [linalg.svdvals])
    @pytest.mark.parametrize('dtype', floating)
    def test_svdvals(self, fun, dtype, rng):
        A = get_random((2, 3, 4, 5), dtype=dtype, rng=rng)
        self.batch_test(fun, A)

    @pytest.mark.parametrize('fun_n_out', [(linalg.orthogonal_procrustes, 2),
                                           (linalg.khatri_rao, 1),
                                           (linalg.solve_continuous_lyapunov, 1),
                                           (linalg.solve_discrete_lyapunov, 1),
                                           (linalg.qz, 4),
                                           (linalg.ordqz, 6)])
    @pytest.mark.parametrize('dtype', floating)
    def test_two_generic_matrix_inputs(self, fun_n_out, dtype, rng):
        fun, n_out = fun_n_out
        A = get_random((2, 3, 4, 4), dtype=dtype, rng=rng)
        B = get_random((2, 3, 4, 4), dtype=dtype, rng=rng)
        self.batch_test(fun, (A, B), n_out=n_out)

    @pytest.mark.parametrize('dtype', floating)
    def test_cossin(self, dtype, rng):
        p, q = 3, 4
        X = get_random((2, 3, 10, 10), dtype=dtype, rng=rng)
        x11, x12, x21, x22 = (X[..., :p, :q], X[..., :p, q:],
                              X[..., p:, :q], X[..., p:, q:])
        res = linalg.cossin(X, p, q)
        ref = linalg.cossin((x11, x12, x21, x22))
        for res_i, ref_i in zip(res, ref):
            np.testing.assert_equal(res_i, ref_i)

        for j in range(2):
            for k in range(3):
                ref_jk = linalg.cossin(X[j, k], p, q)
                for res_i, ref_ijk in zip(res, ref_jk):
                    np.testing.assert_equal(res_i[j, k], ref_ijk)

    @pytest.mark.parametrize('dtype', floating)
    def test_sylvester(self, dtype, rng):
        A = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        B = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        C = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        self.batch_test(linalg.solve_sylvester, (A, B, C))

    @pytest.mark.parametrize('fun', [linalg.solve_continuous_are,
                                     linalg.solve_discrete_are])
    @pytest.mark.parametrize('dtype', floating)
    def test_are(self, fun, dtype, rng):
        a = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        b = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        q = get_nearly_hermitian((2, 3, 5, 5), dtype=dtype, atol=0, rng=rng)
        r = get_nearly_hermitian((2, 3, 5, 5), dtype=dtype, atol=0, rng=rng)
        a = a + 5*np.eye(5)  # making these positive definite seems to help
        b = b + 5*np.eye(5)
        q = q + 5*np.eye(5)
        r = r + 5*np.eye(5)
        # can't easily generate valid random e, s
        self.batch_test(fun, (a, b, q, r))

    @pytest.mark.parametrize('dtype', floating)
    def test_rsf2cs(self, dtype, rng):
        A = get_random((2, 3, 4, 4), dtype=dtype, rng=rng)
        T, Z = linalg.schur(A)
        self.batch_test(linalg.rsf2csf, (T, Z), n_out=2)

    @pytest.mark.parametrize('dtype', floating)
    def test_cholesky_banded(self, dtype, rng):
        ab = get_random((5, 4, 3, 6), dtype=dtype, rng=rng)
        ab[..., -1, :] = 10  # make diagonal dominant
        self.batch_test(linalg.cholesky_banded, ab)

    @pytest.mark.parametrize('dtype', floating)
    def test_block_diag(self, dtype, rng):
        a = get_random((1, 3, 1, 3), dtype=dtype, rng=rng)
        b = get_random((2, 1, 3, 6), dtype=dtype, rng=rng)
        c = get_random((1, 1, 3, 2), dtype=dtype, rng=rng)

        # batch_test doesn't have the logic to broadcast just the batch shapes,
        # so do it manually.
        a2 = np.broadcast_to(a, (2, 3, 1, 3))
        b2 = np.broadcast_to(b, (2, 3, 3, 6))
        c2 = np.broadcast_to(c, (2, 3, 3, 2))
        ref = self.batch_test(linalg.block_diag, (a2, b2, c2),
                              check_kwargs=False, broadcast=False)

        # Check that `block_diag` broadcasts the batch shapes as expected.
        res = linalg.block_diag(a, b, c)
        assert_allclose(res, ref)

    @pytest.mark.parametrize('fun_n_out', [(linalg.eigh_tridiagonal, 2),
                                           (linalg.eigvalsh_tridiagonal, 1)])
    @pytest.mark.parametrize('dtype', real_floating)
    # "Only real arrays currently supported"
    def test_eigh_tridiagonal(self, fun_n_out, dtype, rng):
        fun, n_out = fun_n_out
        d = get_random((3, 4, 5), dtype=dtype, rng=rng)
        e = get_random((3, 4, 4), dtype=dtype, rng=rng)
        self.batch_test(fun, (d, e), core_dim=1, n_out=n_out, broadcast=False)

    @pytest.mark.parametrize('bdim', [(5,), (5, 4), (2, 3, 5, 4)])
    @pytest.mark.parametrize('dtype', floating)
    def test_solve(self, bdim, dtype, rng):
        A = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        b = get_random(bdim, dtype=dtype, rng=rng)
        x = linalg.solve(A, b)
        if len(bdim) == 1:
            x = x[..., np.newaxis]
            b = b[..., np.newaxis]
        assert_allclose(A @ x - b, 0, atol=1e-6)
        assert_allclose(x, np.linalg.solve(A, b), atol=2e-6)

    @pytest.mark.parametrize('bdim', [(5,), (5, 4), (2, 3, 5, 4)])
    @pytest.mark.parametrize('dtype', floating)
    def test_lu_solve(self, bdim, dtype, rng):
        A = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        b = get_random(bdim, dtype=dtype, rng=rng)
        lu_and_piv = linalg.lu_factor(A)
        x = linalg.lu_solve(lu_and_piv, b)
        if len(bdim) == 1:
            x = x[..., np.newaxis]
            b = b[..., np.newaxis]
        assert_allclose(A @ x - b, 0, atol=1e-6)
        assert_allclose(x, np.linalg.solve(A, b), atol=2e-6)

    @pytest.mark.parametrize('l_and_u', [(1, 1), ([2, 1, 0], [0, 1 , 2])])
    @pytest.mark.parametrize('bdim', [(5,), (5, 4), (2, 3, 5, 4)])
    @pytest.mark.parametrize('dtype', floating)
    def test_solve_banded(self, l_and_u, bdim, dtype, rng):
        l, u = l_and_u
        ab = get_random((2, 3, 3, 5), dtype=dtype, rng=rng)
        b = get_random(bdim, dtype=dtype, rng=rng)
        x = linalg.solve_banded((l, u), ab, b)
        for i in range(2):
            for j in range(3):
                bij = b if len(bdim) <= 2 else b[i, j]
                lj = l if np.ndim(l) == 0 else l[j]
                uj = u if np.ndim(u) == 0 else u[j]
                xij = linalg.solve_banded((lj, uj), ab[i, j], bij)
                assert_allclose(x[i, j], xij)

    # Can uncomment when `solve_toeplitz` deprecation is done (SciPy 1.17)
    # @pytest.mark.parametrize('separate_r', [False, True])
    # @pytest.mark.parametrize('bdim', [(5,), (5, 4), (2, 3, 5, 4)])
    # @pytest.mark.parametrize('dtype', floating)
    # def test_solve_toeplitz(self, separate_r, bdim, dtype, rng):
    #     c = get_random((2, 3, 5), dtype=dtype, rng=rng)
    #     r = get_random((2, 3, 5), dtype=dtype, rng=rng)
    #     c_or_cr = (c, r) if separate_r else c
    #     b = get_random(bdim, dtype=dtype, rng=rng)
    #     x = linalg.solve_toeplitz(c_or_cr, b)
    #     for i in range(2):
    #         for j in range(3):
    #             bij = b if len(bdim) <= 2 else b[i, j]
    #             c_or_cr_ij = (c[i, j], r[i, j]) if separate_r else c[i, j]
    #             xij = linalg.solve_toeplitz(c_or_cr_ij, bij)
    #             assert_allclose(x[i, j], xij)

    @pytest.mark.parametrize('bdim', [(5,), (5, 4), (2, 3, 5, 4)])
    @pytest.mark.parametrize('dtype', floating)
    def test_cho_solve(self, bdim, dtype, rng):
        A = get_nearly_hermitian((2, 3, 5, 5), dtype=dtype, atol=0, rng=rng)
        A = A + 5*np.eye(5)
        c_and_lower = linalg.cho_factor(A)
        b = get_random(bdim, dtype=dtype, rng=rng)
        x = linalg.cho_solve(c_and_lower, b)
        if len(bdim) == 1:
            x = x[..., np.newaxis]
            b = b[..., np.newaxis]
        assert_allclose(A @ x - b, 0, atol=1e-6)
        assert_allclose(x, np.linalg.solve(A, b), atol=2e-6)

    @pytest.mark.parametrize('lower', [False, True])
    @pytest.mark.parametrize('bdim', [(5,), (5, 4), (2, 3, 5, 4)])
    @pytest.mark.parametrize('dtype', floating)
    def test_cho_solve_banded(self, lower, bdim, dtype, rng):
        A = get_random((2, 3, 3, 5), dtype=dtype, rng=rng)
        row_diag = 0 if lower else -1
        A[:, :, row_diag] = 10
        cb = linalg.cholesky_banded(A, lower=lower)
        b = get_random(bdim, dtype=dtype, rng=rng)
        x = linalg.cho_solve_banded((cb, lower), b)
        for i in range(2):
            for j in range(3):
                bij = b if len(bdim) <= 2 else b[i, j]
                xij = linalg.cho_solve_banded((cb[i, j], lower), bij)
                assert_allclose(x[i, j], xij)

    @pytest.mark.parametrize('bdim', [(5,), (5, 4), (2, 3, 5, 4)])
    @pytest.mark.parametrize('dtype', floating)
    def test_solveh_banded(self, bdim, dtype, rng):
        A = get_random((2, 3, 3, 5), dtype=dtype, rng=rng)
        A[:, :, -1] = 10
        b = get_random(bdim, dtype=dtype, rng=rng)
        x = linalg.solveh_banded(A, b)
        for i in range(2):
            for j in range(3):
                bij = b if len(bdim) <= 2 else b[i, j]
                xij = linalg.solveh_banded(A[i, j], bij)
                assert_allclose(x[i, j], xij)

    @pytest.mark.parametrize('bdim', [(5,), (5, 4), (2, 3, 5, 4)])
    @pytest.mark.parametrize('dtype', floating)
    def test_solve_triangular(self, bdim, dtype, rng):
        A = get_random((2, 3, 5, 5), dtype=dtype, rng=rng)
        A = np.tril(A)
        b = get_random(bdim, dtype=dtype, rng=rng)
        x = linalg.solve_triangular(A, b, lower=True)
        if len(bdim) == 1:
            x = x[..., np.newaxis]
            b = b[..., np.newaxis]
        atol = 1e-10 if dtype in (np.complex128, np.float64) else 2e-4
        assert_allclose(A @ x - b, 0, atol=atol)
        assert_allclose(x, np.linalg.solve(A, b), atol=5*atol)

    @pytest.mark.parametrize('bdim', [(4,), (4, 3), (2, 3, 4, 3)])
    @pytest.mark.parametrize('dtype', floating)
    def test_lstsq(self, bdim, dtype, rng):
        A = get_random((2, 3, 4, 5), dtype=dtype, rng=rng)
        b = get_random(bdim, dtype=dtype, rng=rng)
        res = linalg.lstsq(A, b)
        x = res[0]
        if len(bdim) == 1:
            x = x[..., np.newaxis]
            b = b[..., np.newaxis]
        assert_allclose(A @ x - b, 0, atol=2e-6)
        assert len(res) == 4
